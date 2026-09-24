#!/usr/bin/env bash
#
# One-command redeploy: recreates the GKE cluster + registry from scratch
# (terraform apply), rebuilds and pushes the image, and brings the app up
# on Kubernetes - everything from Phase 5 Steps 2-4, minus the load test
# itself. This exists because `terraform destroy` deletes *everything*
# (cluster, registry, and the image stored in it), so getting back to a
# running app isn't a "resume" - it's a full rebuild, and doing that by
# hand each time is exactly the kind of repetitive, error-prone process a
# script should own instead.
#
# Deliberately does NOT run `terraform destroy` - tearing down is a
# separate, deliberate decision the user makes themselves, not something
# that should ever happen as a side effect of running a "start it up"
# script.
#
# Usage: ./deploy.sh   (run from the repo root, on the Mac - not the
# Linux file-editing bridge - since it needs gcloud/docker/kubectl/
# terraform all actually installed and authenticated.)

set -euo pipefail

# Always run from the directory this script itself lives in, so it works
# the same whether it's invoked as ./deploy.sh or from somewhere else.
cd "$(dirname "${BASH_SOURCE[0]}")"

# These match terraform/main.tf and k8s/deployment.yaml exactly - if you
# ever rename the project, cluster, or repo, update them in both places.
PROJECT="clinical-evidence-agent-2026"
REGION="us-central1"
CLUSTER="clinical-evidence-agent"
IMAGE="us-central1-docker.pkg.dev/${PROJECT}/clinical-evidence-agent/clinical-evidence-agent:latest"
SERVICE_NAME="clinical-evidence-agent"
SECRET_NAME="clinical-evidence-agent-secrets"

echo "==> [1/7] Checking required tools are installed..."
for tool in terraform gcloud docker kubectl; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing required tool: $tool. Install it before running this script."
    exit 1
  fi
done
if [ ! -f .env ]; then
  echo "Missing .env file in the repo root - needed to create the Kubernetes Secret."
  exit 1
fi

echo "==> [2/7] terraform apply (recreating the GKE cluster + Artifact Registry repo)..."
(cd terraform && terraform init -input=false && terraform apply -auto-approve)

echo "==> [3/7] Pointing kubectl at the new cluster..."
gcloud container clusters get-credentials "$CLUSTER" --region "$REGION" --project "$PROJECT"

echo "==> [4/7] Authenticating Docker against Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "==> [5/7] Building and pushing the image (linux/amd64, since GKE nodes are amd64)..."
docker buildx build --platform linux/amd64 -t "$IMAGE" --push .

echo "==> [6/7] Creating the Kubernetes Secret from .env..."
# --dry-run=client -o yaml | kubectl apply -f - makes this safe to re-run:
# it updates the Secret if it already exists instead of erroring out.
kubectl create secret generic "$SECRET_NAME" --from-env-file=.env \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> [7/7] Applying the Deployment, Service, and HPA..."
kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml -f k8s/hpa.yaml
kubectl rollout status deployment/clinical-evidence-agent --timeout=180s

echo "==> Waiting for the LoadBalancer to get a public IP (usually under a minute)..."
EXTERNAL_IP=""
for _ in $(seq 1 30); do
  EXTERNAL_IP=$(kubectl get service "$SERVICE_NAME" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
  [ -n "$EXTERNAL_IP" ] && break
  sleep 10
done
if [ -z "$EXTERNAL_IP" ]; then
  echo "Timed out waiting for an external IP. Check manually with: kubectl get service $SERVICE_NAME"
  exit 1
fi
echo "External IP: $EXTERNAL_IP"

echo "==> Waiting for the app to actually answer (the LB needs a short warm-up after new pods appear)..."
for _ in $(seq 1 12); do
  if curl -sf -m 10 "http://${EXTERNAL_IP}/health" >/dev/null 2>&1; then
    echo ""
    echo "App is up: http://${EXTERNAL_IP}/health"
    echo "Try it:    curl -X POST http://${EXTERNAL_IP}/ask -H 'Content-Type: application/json' -d '{\"question\": \"...\", \"role\": \"clinician\"}'"
    exit 0
  fi
  sleep 10
done

echo "Deployed, but /health isn't responding yet - give it another minute, then try:"
echo "curl http://${EXTERNAL_IP}/health"
