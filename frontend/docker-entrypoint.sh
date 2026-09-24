#!/bin/sh
# The official nginx image automatically runs every executable script in
# /docker-entrypoint.d/ before nginx starts - that's the hook this script
# uses, rather than replacing nginx's own startup process. `envsubst`
# substitutes the real API_URL environment variable's value into the
# ${API_URL} placeholder in the template, writing the real config.js file
# nginx will actually serve.
set -eu
: "${API_URL:?API_URL environment variable must be set (e.g. the backend's LoadBalancer URL)}"
envsubst '${API_URL}' < /etc/nginx/config.js.template > /usr/share/nginx/html/config.js
