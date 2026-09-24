# ---- Stage 1: build the static React app ----
# A React app has no server-side logic at all once built - "npm run
# build" produces a folder of plain HTML/CSS/JS files. This first stage
# exists only to run that build; its final image is thrown away and only
# the output files (dist/) get copied into the real image below. This
# keeps Node, npm, and every dev dependency (TypeScript, Vite, etc.) out
# of the image that actually gets deployed and run.
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

# ---- Stage 2: serve the built files with nginx ----
# nginx is a lightweight, battle-tested web server - more than enough for
# serving a handful of static files, and far smaller/cheaper than running
# a whole Node process just to hand out files that never change.
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html

# This is the runtime-configuration piece described in src/api.ts: rather
# than baking the backend's URL into the JavaScript bundle at build time
# (which would mean rebuilding the whole image every time the backend's
# address changes - e.g. after a fresh `terraform apply`), this template
# gets turned into a real config.js file *when the container starts*,
# using whatever API_URL environment variable it's given then. The exact
# same built image can be pointed at any backend this way.
COPY config.js.template /etc/nginx/config.js.template
COPY docker-entrypoint.sh /docker-entrypoint.d/40-inject-api-url.sh
RUN chmod +x /docker-entrypoint.d/40-inject-api-url.sh

EXPOSE 80
