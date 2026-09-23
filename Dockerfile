# Base image: start from an official, ready-made box that already has
# Python 3.12 installed - the same version this project's venv uses
# (db/schema.sql/CONNECTION etc. don't care about Python version, but
# matching it avoids any "works on 3.12, breaks on 3.11" surprise).
# "slim" means a stripped-down version of that box with only the bare
# essentials, not the full operating system - smaller to download and
# store, which matters once you're pushing images to the cloud.
FROM python:3.12-slim

# Everything from here happens inside a folder called /app inside the
# box. This doesn't need to match anything on your Mac - it's just where
# things live *inside* the container.
WORKDIR /app

# Copy ONLY requirements.txt first, install from it, and only THEN copy
# the rest of the code (below). This looks backwards, but it's a real
# Docker optimization worth understanding: Docker builds an image in
# layers, and reuses a layer instead of rebuilding it if nothing that
# layer depends on has changed. Your Python code (api/, retrieval/, etc.)
# changes constantly as you edit it; your dependency list changes rarely.
# By installing dependencies in their own separate step, before copying
# code, editing a single Python file later won't force Docker to
# re-download and reinstall every package again - only the fast "copy
# code" step reruns pip install stays cached.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the actual application code into the box. This copies from
# your project folder (wherever `docker build` is run from) into /app
# inside the container - everything except what .dockerignore excludes
# (see that file: your .venv, .env, .git, and local data don't belong in
# the image at all).
COPY api/ ./api/
COPY guardrails/ ./guardrails/
COPY retrieval/ ./retrieval/

# Documentation, not enforcement: this line doesn't actually open the
# port by itself, it just states "this container expects to be reached
# on port 8000" - a note to whoever runs it (including Kubernetes,
# later) about which port matters.
EXPOSE 8000

# The command that runs when a container starts from this image.
# --host 0.0.0.0 matters and is easy to get wrong: inside a container,
# "localhost" means "only reachable from inside this exact box." Binding
# to 0.0.0.0 ("any address") is what allows a request arriving from
# *outside* the container - from your Mac's browser, or later from
# Kubernetes - to actually reach the app inside it.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
