#!/usr/bin/env bash
# Deploy a side-by-side copy of Warehouse Ops Copilot ("v2") next to the original deploy.sh release
# (run on the workshop VM). Same recipe as deploy.sh (public python image, code from ConfigMaps,
# VSS creds from a Secret), but every object is suffixed so the original is never touched:
#
#   original (deploy.sh)                 v2 (this script)
#   deploy/svc/ingress warehouse-ops     warehouse-ops-v2         labels app=warehouse-ops-v2
#   cm warehouse-ops-code / -data        warehouse-ops-v2-code / -v2-data   (snapshot of app/ at deploy time)
#   secret warehouse-ops-vss-creds       reused read-only if present, else warehouse-ops-v2-vss-creds
#   http://<team host>/app/              http://<team host>/app-v2/
#
# Usage:
#   ./deploy_v2.sh               deploy / redeploy v2 (idempotent; never modifies the original)
#   ./deploy_v2.sh dry-run       server-side dry run of every v2 object, nothing is changed
#   ./deploy_v2.sh render        print the v2 manifests (no cluster needed; TEAM_USER=team-N if no /config)
#   ./deploy_v2.sh status        show original and v2 objects side by side
#   ./deploy_v2.sh promote       back up the original code/data ConfigMaps to warehouse-ops-*-prev,
#                                copy v2's snapshot over them and restart deploy/warehouse-ops
#   ./deploy_v2.sh rollback      restore warehouse-ops-*-prev into the original and restart it
#
# On the VM (separate checkout of branch warehouse-ops-v2; ~/warehouse-ops-src stays as is):
#   git clone -b warehouse-ops-v2 github-warehouse-ops:huixu11/vast-builders-challenge.git ~/warehouse-ops-v2-src
#   bash ~/warehouse-ops-v2-src/tools/warehouse-ops/deploy_v2.sh dry-run
#   bash ~/warehouse-ops-v2-src/tools/warehouse-ops/deploy_v2.sh
#   update:   git -C ~/warehouse-ops-v2-src pull && bash ~/warehouse-ops-v2-src/tools/warehouse-ops/deploy_v2.sh
#   promote:  bash ~/warehouse-ops-v2-src/tools/warehouse-ops/deploy_v2.sh promote
#   rollback: bash ~/warehouse-ops-v2-src/tools/warehouse-ops/deploy_v2.sh rollback
#
# Env: V2_SUFFIX (default v2 -> names warehouse-ops-v2, path /app-v2), V2_OWN_SECRET=1 to build a
# dedicated Secret from /config instead of reusing the original one.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HERE/app"
BASE_NAME="warehouse-ops"
SUFFIX="${V2_SUFFIX:-v2}"
APP_NAME="${BASE_NAME}-${SUFFIX}"
APP_PATH="/app-${SUFFIX}"
APP_PORT=8080
MODE="${1:-deploy}"

case "$MODE" in deploy|dry-run|render|status|promote|rollback) ;; *) sed -n '2,30p' "$0"; exit 2 ;; esac

TEAM_CONFIG=""
if [[ -d /config ]]; then
  TEAM_CONFIGS=()
  while IFS= read -r f; do TEAM_CONFIGS+=("$f"); done < <(find /config -maxdepth 1 -type f -name '*.config' | sort)
  (( ${#TEAM_CONFIGS[@]} == 1 )) || { echo "expected exactly one /config/*.config"; exit 1; }
  TEAM_CONFIG="${TEAM_CONFIGS[0]}"
fi
cfg() { [[ -n "$TEAM_CONFIG" ]] || return 0; grep "^$1=" "$TEAM_CONFIG" | head -n1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//' || true; }
env_or_cfg() { if [[ -n "${!1:-}" ]]; then echo "${!1}"; else cfg "$1"; fi; }

TEAM_USER="${TEAM_USER:-$(cfg USERNAME)}"
[[ -n "$TEAM_USER" ]] || { echo "no /config/*.config with USERNAME (set TEAM_USER=team-N for 'render')"; exit 1; }
NS="$TEAM_USER"
APP_HOST="video-lab-team-${TEAM_USER#team-}.cosmos.vastdata.com"

if [[ "$MODE" != render ]]; then
  if [[ -z "${KUBECONFIG:-}" ]]; then
    if [[ -f "/config/${NS}-k8s.yaml" ]]; then export KUBECONFIG="/config/${NS}-k8s.yaml";
    elif [[ -f /config/kubeconfig ]]; then export KUBECONFIG=/config/kubeconfig; fi
  fi
  kubectl -n "$NS" get pods >/dev/null
fi

WORK="$(umask 077; mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
k() { kubectl -n "$NS" "$@"; }

# ---------------------------------------------------------------- promote / rollback / status
copy_cm() {  # src dst label — copies data+binaryData only (kubectl-only, no jq/python on the VM)
  local dir="$WORK/cm-$2"; mkdir -p "$dir"
  local keys key
  keys="$(k get configmap "$1" -o go-template='{{range $k, $v := .data}}{{$k}}{{"\n"}}{{end}}')"
  while IFS= read -r key; do [[ -n "$key" ]] || continue
    k get configmap "$1" -o go-template="{{index .data \"$key\"}}" > "$dir/$key"; done <<< "$keys"
  keys="$(k get configmap "$1" -o go-template='{{range $k, $v := .binaryData}}{{$k}}{{"\n"}}{{end}}')"
  while IFS= read -r key; do [[ -n "$key" ]] || continue
    k get configmap "$1" -o go-template="{{index .binaryData \"$key\"}}" | base64 -d > "$dir/$key"; done <<< "$keys"
  kubectl create configmap "$2" --from-file="$dir" --dry-run=client -o yaml \
    | kubectl label --local -f - app="$3" -o yaml \
    | k apply --server-side --force-conflicts --field-manager="${APP_NAME}-promote" -f -
}

case "$MODE" in
  status)
    k get deploy,svc,ingress,configmap -l "app in (${BASE_NAME},${APP_NAME})" -o wide || true
    k get configmap "${BASE_NAME}-code" "${APP_NAME}-code" \
      -o custom-columns='NAME:.metadata.name,GIT:.metadata.annotations.warehouse-ops/git-rev,SNAPSHOT:.metadata.annotations.warehouse-ops/snapshot-at' 2>/dev/null || true
    exit 0 ;;
  promote)
    for part in code data; do
      if k get configmap "${BASE_NAME}-${part}" >/dev/null 2>&1; then
        copy_cm "${BASE_NAME}-${part}" "${BASE_NAME}-${part}-prev" "${BASE_NAME}-prev"
      fi
      if k get configmap "${APP_NAME}-${part}" >/dev/null 2>&1; then
        copy_cm "${APP_NAME}-${part}" "${BASE_NAME}-${part}" "$BASE_NAME"
      fi
    done
    k rollout restart deploy/"$BASE_NAME" && k rollout status deploy/"$BASE_NAME" --timeout=300s
    echo "Promoted ${APP_NAME} -> ${BASE_NAME} (/app). Undo with: $0 rollback"
    exit 0 ;;
  rollback)
    k get configmap "${BASE_NAME}-code-prev" >/dev/null || { echo "no ${BASE_NAME}-code-prev backup"; exit 1; }
    for part in code data; do
      if k get configmap "${BASE_NAME}-${part}-prev" >/dev/null 2>&1; then
        copy_cm "${BASE_NAME}-${part}-prev" "${BASE_NAME}-${part}" "$BASE_NAME"
      fi
    done
    k rollout restart deploy/"$BASE_NAME" && k rollout status deploy/"$BASE_NAME" --timeout=300s
    echo "Restored ${BASE_NAME} from the -prev backup."
    exit 0 ;;
esac

# ---------------------------------------------------------------- snapshot app/ and build manifests
# Copy app/ once so concurrent edits can't produce a mixed code/data release.
SNAP="$WORK/snapshot"; GZ_DIR="$WORK/gz"; mkdir -p "$SNAP" "$GZ_DIR"
find "$APP_DIR" -maxdepth 1 -type f \( -name '*.py' -o -name '*.html' -o -name '*.js' -o -name '*.css' \
  -o -name '*.json' -o -name 'requirements.txt' \) -exec cp -p {} "$SNAP"/ \;
GIT_REV="$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [[ -n "$(git -C "$HERE" status --porcelain -- app 2>/dev/null)" ]]; then GIT_REV="${GIT_REV}-dirty"; fi
SNAP_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

CODE_FILES=(); DATA_FILES=()
for f in "$SNAP"/*; do case "$(basename "$f")" in data_*.json) DATA_FILES+=("$f") ;; *) CODE_FILES+=("$f") ;; esac; done
for f in ${DATA_FILES[@]+"${DATA_FILES[@]}"}; do gzip -9c "$f" > "$GZ_DIR/$(basename "$f").gz"; done
(( ${#DATA_FILES[@]} )) || echo "warning: no app/data_*.json in snapshot; v2 will start with empty dashboards"

MANIFESTS="$WORK/manifests"; mkdir -p "$MANIFESTS"
configmap_yaml() {  # name, files...
  local name="$1"; shift
  local total; total=$(cat "$@" | wc -c | tr -d ' ')
  echo "ConfigMap ${name}: $# files, ${total} bytes" >&2
  (( total < 1000000 )) || { echo "${name} is too large for a ConfigMap" >&2; exit 1; }
  local from=(); for f in "$@"; do from+=("--from-file=$f"); done
  kubectl create configmap "$name" "${from[@]}" --dry-run=client -o yaml \
    | kubectl label --local -f - app="$APP_NAME" -o yaml \
    | kubectl annotate --local -f - warehouse-ops/git-rev="$GIT_REV" warehouse-ops/snapshot-at="$SNAP_AT" -o yaml
}
configmap_yaml "${APP_NAME}-code" "${CODE_FILES[@]}" > "$MANIFESTS/10-code.yaml"
if (( ${#DATA_FILES[@]} )); then configmap_yaml "${APP_NAME}-data" "$GZ_DIR"/*.gz > "$MANIFESTS/11-data.yaml"; fi

# Secret: reference the original read-only unless asked (or forced, if it doesn't exist) to build our own.
SECRET_NAME="${BASE_NAME}-vss-creds"
if [[ "${V2_OWN_SECRET:-0}" == 1 ]] || { [[ "$MODE" != render ]] && ! k get secret "$SECRET_NAME" >/dev/null 2>&1; }; then
  SECRET_NAME="${APP_NAME}-vss-creds"
  if [[ "$MODE" != render ]]; then
    [[ -n "$TEAM_CONFIG" ]] || { echo "need /config/*.config to build ${SECRET_NAME}"; exit 1; }
    ENV_FILE="$WORK/creds.env"
    {
      echo "VSS_URL=$(cfg INGRESS_URL)"
      echo "VSS_USERNAME=$TEAM_USER"
      echo "VSS_PASSWORD=$(cfg PASSWORD)"
      echo "GPU_BEARER_TOKEN=$(cfg GPU_BEARER_TOKEN)"
      echo "PIPELINE=$(cfg PIPELINE)"
      for key in WANDB_API_KEY WANDB_TEAM WANDB_PROJECT WANDB_MODEL; do
        value="$(env_or_cfg "$key")"
        if [[ -n "$value" ]]; then echo "$key=$value"; fi
      done
    } > "$ENV_FILE"
    kubectl create secret generic "$SECRET_NAME" --from-env-file="$ENV_FILE" --dry-run=client -o yaml \
      > "$MANIFESTS/05-secret.yaml"
  fi
fi
echo "Secret: ${SECRET_NAME}" >&2

cat > "$MANIFESTS/20-app.yaml" <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${APP_NAME}
  labels: {app: ${APP_NAME}}
  annotations: {warehouse-ops/git-rev: "${GIT_REV}", warehouse-ops/snapshot-at: "${SNAP_AT}"}
spec:
  replicas: 1
  selector:
    matchLabels: {app: ${APP_NAME}}
  template:
    metadata:
      labels: {app: ${APP_NAME}}
      annotations: {warehouse-ops/snapshot-at: "${SNAP_AT}"}
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
        - secretRef: {name: ${SECRET_NAME}}
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
      - path: ${APP_PATH}(/|$)(.*)
        pathType: ImplementationSpecific
        backend:
          service:
            name: ${APP_NAME}
            port: {number: 80}
EOF

if [[ "$MODE" == render ]]; then
  for f in "$MANIFESTS"/*.yaml; do echo "---"; cat "$f"; done
  exit 0
fi

# Guard: everything we are about to apply must carry the v2 name, so the original can't be hit.
BAD="$(grep -h '^  name: ' "$MANIFESTS"/*.yaml | grep -v "^  name: ${APP_NAME}-\{0,1\}" || true)"
[[ -z "$BAD" ]] || { echo "refusing to apply non-v2 objects:"; echo "$BAD"; exit 1; }

if [[ "$MODE" == dry-run ]]; then
  for f in "$MANIFESTS"/*.yaml; do
    k apply --server-side --force-conflicts --field-manager="$APP_NAME" --dry-run=server -f "$f"
  done
  echo "Dry run OK: would serve http://${APP_HOST}${APP_PATH}/ (snapshot ${GIT_REV} @ ${SNAP_AT})"
  exit 0
fi

EXISTED="$(k get deploy "$APP_NAME" -o name 2>/dev/null || true)"
for f in "$MANIFESTS"/*.yaml; do
  k apply --server-side --force-conflicts --field-manager="$APP_NAME" -f "$f"
done
# The pod-template snapshot annotation already forces a new rollout; this covers manual re-runs with no diff.
if [[ -n "$EXISTED" ]]; then k rollout restart deploy/"$APP_NAME"; fi
k rollout status deploy/"$APP_NAME" --timeout=300s \
  || { k logs -l app="$APP_NAME" --tail=80 || true; exit 1; }
k get pods,svc,ingress -l app="$APP_NAME"

CODE=000
for _ in $(seq 1 20); do
  CODE="$(curl -sS -o /dev/null -w '%{http_code}' "http://${APP_HOST}${APP_PATH}/health" || true)"
  [[ "$CODE" == 200 ]] && break
  sleep 3
done
echo "GET http://${APP_HOST}${APP_PATH}/health -> ${CODE}"
if [[ "$CODE" != 200 ]]; then
  k get endpoints "$APP_NAME" || true
  k logs -l app="$APP_NAME" --tail=40 || true
fi
echo "v2 (${GIT_REV} @ ${SNAP_AT}): http://${APP_HOST}${APP_PATH}/   original untouched at ${APP_PATH%-*}/"
