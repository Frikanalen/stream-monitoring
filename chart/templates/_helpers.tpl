{{- /*
Every object, the Service label Prometheus copies onto each series, and so
every alert and dashboard query, is keyed on this name. nameOverride lets a
second release watch another stream in the same namespace.
*/ -}}
{{- define "stream-monitoring.name" -}}
{{ .Values.nameOverride | default "stream-monitoring" }}
{{- end }}

{{- define "stream-monitoring.labels" -}}
app.kubernetes.io/name: {{ include "stream-monitoring.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

