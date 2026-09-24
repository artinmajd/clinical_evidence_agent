#!/usr/bin/env bash
#
# One-command redeploy: recreates the GKE cluster + registry from scratch
# (terraform apply), rebuilds and pushes both the backend and frontend
# images, and brings the whole app up on Kubernetes - everything from
# Phase 5 Steps 2-4 plus the frontend, minus the load test itself. This
# exists because `terraform destroy` deletes *everything* (cluster,
# registry, and every image stored in it), so getting back to a running
# app isn't a "resume" - it's a full rebuild, and doing that by hand each
# time is exactly the kind of repetitive, error-prone process a script
# should own instead.
#
# Deliberately does NOT run `terraform destroy` - tearing down is a
# separate, deliberate decision the user makes themselves, not something
# that should ever happen as a side effect of running a "start it up"
# script.
#
# Usage: ./deploy.sh   (run from the repo root, on the Mac - not the
# Linux file-editing bridge - since it needs gcloud/docker/kubectl/
# terraform/node all actually installed and authenticated.)

set -euo pipefail

# Always run from the directory this script itself lives in, so it works
# the same whether it's invoked as ./deploy.sh or from somewhere else.
cd "$(dirname "${BASH_SOURCE[0]}")"

# These match terraform/main.tf, k8s/deployment.yaml, and
# k8s/frontend-deployment.yaml exactly - if you ever rename the project,
# cluster, or repo, update them in all of those places too.
PROJECT="clinical-evidence-agent-2026"
REGION="us-central1"
CLUSTER="clinical-evidence-agent"
BACKEND_IMAGE="us-central1-docker.pkg.dev/${PROJECT}/clinical-evidence-agent/clinical-evidence-agent:latest"
FRONTEND_IMAGE="us-central1-docker.pkg.dev/${PROJECT}/clinical-evidence-agent/clinical-evidence-agent-frontend:latest"
BACKEND_SERVICE="clinical-evidence-agent"
FRONTEND_SERVICE="clinical-evidence-agent-frontend"
SECRET_NAME="clinical-evidence-agent-secrets"

# Polls a Service's status until it gets a public IP from the
# LoadBalancer, then waits for a URL on that IP to actually respond -
# both the "$1" (which Service) and "$2" (which URL to health-check) are
# passed in, since the backend and frontend both need this exact same
# two-stage wait.
#
# Every progress message below is sent to stderr (">&2"), not stdout -
# on purpose. This function's actual "return value" is the final IP,
# handed back via `echo "$ip"` and captured by the caller as
# `RESULT=$(wait_for_service ...)`. Bash command substitution captures
# ALL of a function's stdout, not just its last line - so a status
# message printed with a plain `echo` would silently become part of
# that captured string too, corrupting it into multiple lines of text
# instead of a clean IP address. Sending status output to stderr instead
# keeps it visible in the terminal while keeping stdout clean for the
# one line that's actually meant to be captured.
wait_for_service() {
  local service_name="$1" health_path="$2" ip=""
  echo "    Waiting for $service_name's public IP (usually under a minute)..." >&2
  for _ in $(seq 1 30); do
    ip=$(kubectl get service "$service_name" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
    [ -n "$ip" ] && break
    sleep 10
  done
  if [ -z "$ip" ]; then
    echo "    Timed out waiting for an external IP. Check manually with: kubectl get service $service_name" >&2
    return 1
  fi
  echo "    External IP: $ip" >&2

  echo "    Waiting for it to actually answer (LoadBalancers need a short warm-up after new pods appear)..." >&2
  for _ in $(seq 1 24); do
    if curl -sf -m 10 "http://${ip}${health_path}" >/dev/null 2>&1; then
      echo "$ip"
      return 0
    fi
    sleep 10
  done
  echo "    Deployed, but not responding yet - give it another minute, then try: curl http://${ip}${health_path}" >&2
  echo "$ip"
  return 0
}

echo "==> [1/9] Checking required tools are installed..."
for tool in terraform gcloud docker kubectl node npm; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing required tool: $tool. Install it before running this script."
    exit 1
  fi
done
if [ ! -f .env ]; then
  echo "Missing .env file in the repo root - needed to create the Kubernetes Secret."
  exit 1
fi

echo "==> [2/9] terraform apply (recreating the GKE cluster + Artifact Registry repo)..."
(cd terraform && terraform init -input=false && terraform apply -auto-approve)

echo "==> [3/9] Pointing kubectl at the new cluster..."
gcloud container clusters get-credentials "$CLUSTER" --region "$REGION" --project "$PROJECT"

echo "==> [4/9] Authenticating Docker against Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "==> [5/9] Building and pushing the backend image (linux/amd64, since GKE nodes are amd64)..."
docker buildx build --platform linux/amd64 -t "$BACKEND_IMAGE" --push .

echo "==> [6/9] Deploying the backend: Secret, Deployment, Service, HPA..."
# --dry-run=client -o yaml | kubectl apply -f - makes the Secret step
# safe to re-run: it updates the Secret if it already exists instead of
# erroring out.
kubectl create secret generic "$SECRET_NAME" --from-env-file=.env \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml -f k8s/hpa.yaml
# `kubectl apply` only reacts to changes in the manifest's *text* - since
# the image tag is the mutable ":latest" (identical text every run), a
# code-only change (like the CORS fix that led to writing this comment)
# leaves the manifest looking unchanged to Kubernetes, so it has no
# reason to restart pods or re-pull the image, even though the actual
# image content behind that tag is now different. `rollout restart`
# forces that re-pull explicitly every run, regardless of whether
# anything in the YAML itself changed.
kubectl rollout restart deployment/clinical-evidence-agent
kubectl rollout status deployment/clinical-evidence-agent --timeout=180s

BACKEND_IP=$(wait_for_service "$BACKEND_SERVICE" "/health")
BACKEND_URL="http://${BACKEND_IP}"

echo "==> [7/9] Installing frontend dependencies and building the frontend image..."
(cd frontend && npm install)
docker buildx build --platform linux/amd64 -t "$FRONTEND_IMAGE" --push ./frontend

echo "==> [8/9] Deploying the frontend, pointed at the backend at ${BACKEND_URL}..."
# The frontend manifest has two placeholders (its own image, and the
# backend's URL, which is only known now that step 6 finished) - filled
# in here and piped straight to kubectl rather than written to a file, so
# no copy of the manifest with a real IP baked into it is ever left lying
# around on disk.
sed -e "s|FRONTEND_IMAGE_PLACEHOLDER|${FRONTEND_IMAGE}|" \
    -e "s|BACKEND_URL_PLACEHOLDER|${BACKEND_URL}|" \
    k8s/frontend-deployment.yaml | kubectl apply -f -
kubectl apply -f k8s/frontend-service.yaml
# Same reasoning as the backend's rollout restart above - forces a fresh
# pull of this run's just-pushed frontend image every time.
kubectl rollout restart deployment/clinical-evidence-agent-frontend
kubectl rollout status deployment/clinical-evidence-agent-frontend --timeout=180s

FRONTEND_IP=$(wait_for_service "$FRONTEND_SERVICE" "/")

echo "==> [9/9] Done."
echo ""
echo "Frontend (open this in a browser): http://${FRONTEND_IP}/"
echo "Backend health check:              http://${BACKEND_IP}/health"
