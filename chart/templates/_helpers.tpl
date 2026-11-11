{{- define "stream-monitoring.name" -}}
stream-monitoring
{{- end }}

{{- define "stream-monitoring.labels" -}}
app.kubernetes.io/name: {{ include "stream-monitoring.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

