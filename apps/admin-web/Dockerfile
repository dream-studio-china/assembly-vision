# AssemblyVision admin-web image (design 05 section 10, C1a).
#
# Multi-stage build from the repository root (the pnpm workspace lockfile
# lives at the root): node builds the Vite application; nginx serves the
# static assets and proxies /api to the central-service container so the
# pilot UI shares one origin with the API.
#
# Build: docker build -f apps/admin-web/Dockerfile .

FROM node:22-alpine AS builder

WORKDIR /app
COPY . .

# Install the workspace-pinned pnpm directly; corepack's signature shim is
# unreliable inside the image builder (keyid verification failures).
RUN npm install -g pnpm@10.12.4 \
    && pnpm install --frozen-lockfile --filter admin-web... \
    && VITE_API_MODE=http pnpm --filter admin-web build

FROM nginx:1.27-alpine AS runtime

COPY apps/admin-web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/apps/admin-web/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=4 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
