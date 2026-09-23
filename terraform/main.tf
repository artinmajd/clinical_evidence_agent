# This block does not create anything by itself - it tells Terraform which
# *provider* plugins this file needs and which versions are acceptable.
# A provider is the plugin that knows how to talk to one specific cloud's
# API (here, Google Cloud's). `terraform init` reads this block and
# downloads the matching plugin before anything else can run.
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

# Configures the Google provider itself: which project everything below
# gets created in, and which region to default to. Notice there's no
# password or API key here - the provider authenticates using the
# Application Default Credentials we just set up (`gcloud auth
# application-default login`), the same way the gcloud CLI itself does.
provider "google" {
  project = "clinical-evidence-agent-2026"
  region  = "us-central1"
}

# The actual thing we want to exist: a GKE Autopilot cluster. Everything
# above this point is setup; this `resource` block is the one line in the
# whole file that Terraform turns into a real, billed object in Google
# Cloud once we run `terraform apply`.
resource "google_container_cluster" "primary" {
  name     = "clinical-evidence-agent"
  location = "us-central1"

  # This single flag is what makes it an Autopilot cluster instead of a
  # Standard one - Google manages the underlying nodes automatically, and
  # we're billed per-pod-resource-requested rather than per-node, as
  # covered in NOTES.md.
  enable_autopilot = true

  # By default, recent versions of this provider protect a cluster from
  # being destroyed by `terraform destroy` (a safety net for production
  # clusters people don't want accidentally deleted). We're deliberately
  # turning that off: this cluster's whole purpose is to be spun up for a
  # load test and torn down afterward, per the project plan - the
  # protection would just get in our own way at teardown time.
  deletion_protection = false
}

# The Artifact Registry API is a Google Cloud service like any other - it
# has to be explicitly turned on for this project before we can create a
# repository in it, the same way we manually ran `gcloud services enable`
# for the Kubernetes Engine and Compute Engine APIs earlier. Doing it here
# instead means it's captured in code rather than a one-off command we'd
# have to remember to redo if this project were ever set up from scratch
# on a different GCP project.
resource "google_project_service" "artifact_registry" {
  service = "artifactregistry.googleapis.com"

  # Don't turn the API itself back off if we ever destroy this resource -
  # disabling an entire API is a much bigger, more disruptive action than
  # we want tied to a routine `terraform destroy` of just our own repository.
  disable_on_destroy = false
}

# The actual registry repository - the "storage location" we've been
# discussing that holds our built Docker images so GKE's nodes can pull
# them. `format = "DOCKER"` tells Artifact Registry to speak the standard
# `docker push`/`docker pull` protocol (it also supports other formats,
# like Python packages or npm, which we don't need here). Placed in the
# same region as the cluster deliberately - pulling an image from the
# same region is both faster and avoids cross-region network charges.
resource "google_artifact_registry_repository" "images" {
  location      = "us-central1"
  repository_id = "clinical-evidence-agent"
  format        = "DOCKER"

  # Terraform can't create this repository until the API above is
  # actually enabled - depends_on makes that ordering explicit rather
  # than relying on Terraform to guess it from the resources' fields.
  depends_on = [google_project_service.artifact_registry]
}
