"""Probe a public HLS master playlist the way a player would, and export what it saw.

Every interval: fetch the master playlist, every media playlist it names, and
HEAD the newest segment of each. For each rendition, export its media
sequence and where its newest segment ends (last EXT-X-PROGRAM-DATE-TIME plus
that segment's EXTINF), so Prometheus can tell whether the renditions agree
with each other and with the clock. Freshness alone is not enough: on
2026-11-13 the staging packager kept every playlist advancing for ten hours
with audio ~16 minutes behind video, and no player could start.

Standard library only; serves Prometheus text format on METRICS_PORT.
"""

import datetime
import http.server
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ["HLS_URL"]
INTERVAL = float(os.environ.get("INTERVAL_SECONDS", "10"))
TIMEOUT = float(os.environ.get("TIMEOUT_SECONDS", "8"))
PORT = int(os.environ.get("METRICS_PORT", "9092"))
USER_AGENT = "frikanalen-stream-monitoring/hls-probe"

_lock = threading.Lock()
_metrics = "# no probe has completed yet\n"


def fetch(url, method="GET"):
    request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.status, response.read().decode("utf-8", "replace") if method == "GET" else ""


def parse_pdt(value):
    # 2026-11-13T17:22:18.977+0000; fromisoformat wants +00:00 before 3.11 and
    # still rejects some forms, so normalise the offset first.
    value = value.strip()
    if value.endswith(("Z", "z")):
        value = value[:-1] + "+00:00"
    match = re.search(r"([+-])(\d\d):?(\d\d)$", value)
    if match:
        value = value[: match.start()] + f"{match.group(1)}{match.group(2)}:{match.group(3)}"
    return datetime.datetime.fromisoformat(value).timestamp()


def media_playlists(master_url, text):
    """Rendition name -> absolute URL, for audio renditions and variant streams."""
    found = {}
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("#EXT-X-MEDIA:"):
            match = re.search(r'URI="([^"]+)"', line)
            if match:
                found[match.group(1)] = None
        elif line.startswith("#EXT-X-STREAM-INF:"):
            for following in lines[index + 1 :]:
                if following.strip() and not following.startswith("#"):
                    found[following.strip()] = None
                    break
    result = {}
    for uri in found:
        name = os.path.basename(urllib.parse.urlparse(uri).path).rsplit(".", 1)[0] or uri
        result[name] = urllib.parse.urljoin(master_url, uri)
    return result


def inspect(url, text):
    sequence = None
    pdt = None
    duration = 0.0
    segment = None
    for line in text.splitlines():
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            sequence = int(line.split(":", 1)[1])
        elif line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            pdt = parse_pdt(line.split(":", 1)[1])
            duration = 0.0
        elif line.startswith("#EXTINF:"):
            duration = float(line.split(":", 1)[1].split(",", 1)[0])
        elif line.strip() and not line.startswith("#"):
            segment = urllib.parse.urljoin(url, line.strip())
    end = pdt + duration if pdt is not None else None
    return sequence, end, segment


def probe():
    started = time.time()
    lines = []

    def gauge(name, value, labels=None, help_text=None):
        if help_text:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} gauge")
        if value is None:
            return
        label_text = ""
        if labels:
            label_text = "{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"
        lines.append(f"{name}{label_text} {value}")

    success = 1
    ends = {}
    renditions = {}
    try:
        status, master = fetch(URL)
        master_up = int(status == 200)
        renditions = media_playlists(URL, master)
    except (urllib.error.URLError, OSError, ValueError) as error:
        print(f"master {URL}: {error}", flush=True)
        master_up = 0
    if not master_up or not renditions:
        success = 0

    gauge("frikanalen_hls_master_up", master_up, help_text="Whether the master playlist returned 200.")
    gauge("frikanalen_hls_renditions", len(renditions), help_text="Media playlists named by the master playlist.")

    rows = []
    for name, url in sorted(renditions.items()):
        row = {"rendition": name, "playlist_up": 0, "segment_up": 0, "sequence": None, "end": None}
        try:
            status, text = fetch(url)
            row["playlist_up"] = int(status == 200)
            row["sequence"], row["end"], segment = inspect(url, text)
            if segment:
                status, _ = fetch(segment, method="HEAD")
                row["segment_up"] = int(status == 200)
        except (urllib.error.URLError, OSError, ValueError) as error:
            print(f"{name} {url}: {error}", flush=True)
        if not (row["playlist_up"] and row["segment_up"]):
            success = 0
        if row["end"] is not None:
            ends[name] = row["end"]
        rows.append(row)

    now = time.time()
    metrics = [
        ("frikanalen_hls_playlist_up", "playlist_up", "Whether the media playlist returned 200."),
        ("frikanalen_hls_segment_up", "segment_up", "Whether the newest segment answered HEAD with 200."),
        ("frikanalen_hls_media_sequence", "sequence", "EXT-X-MEDIA-SEQUENCE of the media playlist."),
        (
            "frikanalen_hls_end_timestamp_seconds",
            "end",
            "Where the newest segment ends: last EXT-X-PROGRAM-DATE-TIME plus its EXTINF.",
        ),
    ]
    for metric, key, help_text in metrics:
        gauge(metric, None, help_text=help_text)
        for row in rows:
            gauge(metric, row[key], {"rendition": row["rendition"]})

    gauge(
        "frikanalen_hls_lag_seconds",
        None,
        help_text="Wall clock minus where the newest segment ends; negative means ahead of the clock.",
    )
    for name, end in sorted(ends.items()):
        gauge("frikanalen_hls_lag_seconds", round(now - end, 3), {"rendition": name})
    gauge(
        "frikanalen_hls_rendition_skew_seconds",
        round(max(ends.values()) - min(ends.values()), 3) if len(ends) > 1 else 0,
        help_text="How far apart the renditions' newest segments end.",
    )
    gauge("frikanalen_hls_probe_success", success, help_text="Whether every playlist and newest segment answered 200.")
    gauge("frikanalen_hls_probe_duration_seconds", round(time.time() - started, 3), help_text="Duration of the probe.")
    gauge("frikanalen_hls_probe_timestamp_seconds", round(now, 3), help_text="When the probe finished.")
    return "\n".join(lines) + "\n"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        if self.path not in ("/metrics", "/"):
            self.send_error(404)
            return
        with _lock:
            body = _metrics.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def loop():
    global _metrics
    while True:
        started = time.time()
        try:
            text = probe()
        except Exception as error:  # keep exporting; a crash would hide the failure
            print(f"probe failed: {error!r}", flush=True)
            text = "frikanalen_hls_probe_success 0\n"
        with _lock:
            _metrics = text
        time.sleep(max(0.0, INTERVAL - (time.time() - started)))


if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    http.server.ThreadingHTTPServer(("", PORT), Handler).serve_forever()
