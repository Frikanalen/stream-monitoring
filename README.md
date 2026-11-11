# stream-monitoring

Watches Frikanalen's outgoing MPEG-TS stream around the clock and tells
Prometheus when it stops, freezes, goes silent or decodes with errors:
`ffmpeg_exporter` for the stream's structure, plus an FFmpeg content
analyser for black, frozen and silent output. The Helm chart in
[`chart/`](chart/) also ships its alerting rules and a Grafana dashboard.

The chart was moved here from Frikanalen/gitops (`helm/stream-monitoring`),
with its history in that repository. Where and at which version it runs is
decided in Frikanalen/clusters.
