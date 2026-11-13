# stream-monitoring

Watches Frikanalen's outgoing MPEG-TS stream around the clock and tells
Prometheus when it stops, freezes, goes silent or decodes with errors:
`ffmpeg_exporter` for the stream's structure, plus an FFmpeg content
analyser for black, frozen and silent output. The Helm chart in
[`chart/`](chart/) also ships its alerting rules and a Grafana dashboard.

The chart was moved here from Frikanalen/gitops (`helm/stream-monitoring`),
with its history in that repository. Where and at which version it runs is
decided in Frikanalen/clusters.

## HLS probe

`hlsProbe.enabled` adds a small container that polls the public HLS output
the way a player does: the master playlist, every media playlist it names,
and a HEAD on each newest segment, every 10 seconds. Per rendition it exports
the media sequence and where the newest segment ends by
`EXT-X-PROGRAM-DATE-TIME`, plus the skew between renditions and their
distance from the wall clock (`frikanalen_hls_*`). The rules alert when the
stream is not served, stops advancing, when renditions drift more than
`hlsProbe.maxSkewSeconds` apart, or drift off the clock.

Freshness alone is not enough. On 2026-11-13 the staging packager kept every
playlist advancing for ten hours with audio about 16 minutes behind video;
nothing alerted and no player could start. Because the playlists are fetched
one after another, a skew of one segment (2 s) is normal.

`packagerAlerts.enabled` adds alerts on the packager's own pods (restarts,
not ready, CPU throttling), and `tsMonitor.enabled: false` turns off the
MPEG-TS monitoring where there is no TS to watch, as on staging.
