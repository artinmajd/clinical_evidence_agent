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
