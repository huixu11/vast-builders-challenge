#!/usr/bin/env bash
# Deploy Warehouse Ops Copilot into this team's namespace (run on the workshop VM).
# Follows .cursor/skills/deployment/deploy-app-no-registry: public python image, code from a
# ConfigMap, VSS + GPU credentials from a Secret, Ingress path /app on the team host.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HERE/app"
APP_NAME="${APP_NAME:-warehouse-ops}"
APP_PORT=8080

mapfile -t TEAM_CONFIGS < <(find /config -maxdepth 1 -type f -name '*.config' | sort)
(( ${#TEAM_CONFIGS[@]} == 1 )) || { echo "expected exactly one /config/*.config"; exit 1; }
TEAM_CONFIG="${TEAM_CONFIGS[0]}"
cfg() { grep "^$1=" "$TEAM_CONFIG" | head -n1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//' || true; }
# W&B keys are often exported in the VM environment rather than written to the team config.
env_or_cfg() { if [[ -n "${!1:-}" ]]; then echo "${!1}"; else cfg "$1"; fi; }

TEAM_USER="$(cfg USERNAME)"
[[ -n "$TEAM_USER" ]] || { echo "USERNAME missing from $TEAM_CONFIG"; exit 1; }
NS="$TEAM_USER"
APP_HOST="video-lab-team-${TEAM_USER#team-}.cosmos.vastdata.com"

if [[ -z "${KUBECONFIG:-}" ]]; then
  if [[ -f "/config/${NS}-k8s.yaml" ]]; then export KUBECONFIG="/config/${NS}-k8s.yaml";
  elif [[ -f /config/kubeconfig ]]; then export KUBECONFIG=/config/kubeconfig; fi
fi
kubectl -n "$NS" get pods >/dev/null

ENV_FILE="$(umask 077; mktemp)"
GZ_DIR="$(mktemp -d)"
trap 'rm -rf "$ENV_FILE" "$GZ_DIR"' EXIT

# Kubernetes caps each ConfigMap at ~1 MiB: code goes in as-is, the analyzer's data_*.json gzipped
# into a second ConfigMap that the pod unpacks at startup.
apply_configmap() {  # name, files...
  local name="$1"; shift
  local total; total=$(cat "$@" | wc -c)
  echo "ConfigMap ${name}: $# files, ${total} bytes"
  (( total < 1000000 )) || { echo "${name} is too large for a ConfigMap"; exit 1; }
  local from=(); for f in "$@"; do from+=("--from-file=$f"); done
  # Server-side apply avoids the 256 KiB last-applied-configuration annotation limit.
  kubectl -n "$NS" create configmap "$name" "${from[@]}" --dry-run=client -o yaml \
    | kubectl apply --server-side --force-conflicts -f -
}

mapfile -t CODE_FILES < <(find "$APP_DIR" -maxdepth 1 -type f ! -name 'data_*.json' \
  \( -name '*.py' -o -name '*.html' -o -name '*.js' -o -name '*.css' -o -name '*.json' -o -name 'requirements.txt' \) | sort)
apply_configmap "${APP_NAME}-code" "${CODE_FILES[@]}"

mapfile -t DATA_FILES < <(find "$APP_DIR" -maxdepth 1 -type f -name 'data_*.json' | sort)
if (( ${#DATA_FILES[@]} )); then
  for f in "${DATA_FILES[@]}"; do gzip -9c "$f" > "$GZ_DIR/$(basename "$f").gz"; done
  apply_configmap "${APP_NAME}-data" "$GZ_DIR"/*.gz
else
  echo "warning: no app/data_*.json yet; the app will start with empty dashboards"
fi

{
  echo "VSS_URL=$(cfg INGRESS_URL)"
  echo "VSS_USERNAME=$TEAM_USER"
  echo "VSS_PASSWORD=$(cfg PASSWORD)"
  echo "GPU_BEARER_TOKEN=$(cfg GPU_BEARER_TOKEN)"
  for key in WANDB_API_KEY WANDB_TEAM WANDB_PROJECT WANDB_MODEL; do
    value="$(env_or_cfg "$key")"
    if [[ -n "$value" ]]; then echo "$key=$value"; fi
  done
} > "$ENV_FILE"
kubectl -n "$NS" create secret generic "${APP_NAME}-vss-creds" --from-env-file="$ENV_FILE" --dry-run=client -o yaml \
  | kubectl apply --server-side --force-conflicts -f -

kubectl -n "$NS" apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${APP_NAME}
  labels: {app: ${APP_NAME}}
spec:
  replicas: 1
  selector:
    matchLabels: {app: ${APP_NAME}}
  template:
    metadata:
      labels: {app: ${APP_NAME}}
    spec:
      containers:
      - name: app
        image: python:3.12-slim
        imagePullPolicy: IfNotPresent
        ports: [{containerPort: ${APP_PORT}}]
        env:
        - {name: PORT, value: "${APP_PORT}"}
        - {name: DATA_DIR, value: /appdata}
        - {name: CLIP_CACHE_MB, value: "800"}
        envFrom:
        - secretRef: {name: ${APP_NAME}-vss-creds}
        volumeMounts:
        - {name: code, mountPath: /code}
        - {name: data, mountPath: /data}
        - {name: appdata, mountPath: /appdata}
        workingDir: /code
        command: ["bash", "-c"]
        args:
        - |
          set -euo pipefail
          for f in /data/*.gz; do
            [ -e "\$f" ] || continue
            gzip -dc "\$f" > "/appdata/\$(basename "\$f" .gz)"
          done
          if [ -f requirements.txt ]; then pip install --no-cache-dir -q -r requirements.txt; fi
          exec python main.py
        readinessProbe:
          httpGet: {path: /health, port: ${APP_PORT}}
          initialDelaySeconds: 15
          periodSeconds: 10
      volumes:
      - name: code
        configMap: {name: ${APP_NAME}-code}
      - name: data
        configMap: {name: ${APP_NAME}-data, optional: true}
      - name: appdata
        emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: ${APP_NAME}
  labels: {app: ${APP_NAME}}
spec:
  selector: {app: ${APP_NAME}}
  ports: [{name: http, port: 80, targetPort: ${APP_PORT}}]
  type: ClusterIP
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ${APP_NAME}
  labels: {app: ${APP_NAME}}
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /\$2
    nginx.ingress.kubernetes.io/proxy-body-size: 16m
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
spec:
  ingressClassName: nginx
  rules:
  - host: ${APP_HOST}
    http:
      paths:
      - path: /app(/|$)(.*)
        pathType: ImplementationSpecific
        backend:
          service:
            name: ${APP_NAME}
            port: {number: 80}
EOF

kubectl -n "$NS" rollout restart deploy/"$APP_NAME"
kubectl -n "$NS" rollout status deploy/"$APP_NAME" --timeout=300s \
  || { kubectl -n "$NS" logs -l app="$APP_NAME" --tail=80 || true; exit 1; }
kubectl -n "$NS" get pods,svc,ingress -l app="$APP_NAME"
curl -sS -o /dev/null -w "GET http://${APP_HOST}/app/health -> %{http_code}\n" "http://${APP_HOST}/app/health" || true
echo "Open https://workshop.thecosmoslabs.com and click the App button."
