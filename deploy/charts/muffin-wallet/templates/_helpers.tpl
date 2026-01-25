{{- define "muffin-wallet.name" -}}
muffin-wallet
{{- end }}

{{- define "muffin-wallet.fullname" -}}
{{ .Release.Name }}
{{- end }}

{{- define "muffin-wallet.labels" -}}
app.kubernetes.io/name: {{ include "muffin-wallet.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "muffin-wallet.selectorLabels" -}}
app.kubernetes.io/name: {{ include "muffin-wallet.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "muffin-wallet.secretName" -}}
{{ include "muffin-wallet.fullname" . }}-secret
{{- end }}

{{- define "muffin-wallet.envConfigMapName" -}}
{{ include "muffin-wallet.fullname" . }}-env
{{- end }}
