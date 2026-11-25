# syntax=docker/dockerfile:1
#
# ClipsAI Browser Studio (SvelteKit 3 + FFmpeg.wasm + IndiePost/DeepSeek proxy).
#
# Build:
#   docker build -t clipsai-web ./web
#
# Run:
#   docker run --rm -p 3000:3000 --env-file .env clipsai-web

FROM node:22-slim AS builder

WORKDIR /app

# Copy scripts before `npm ci` so the postinstall hook can sync @ffmpeg/core-mt
# assets into static/ffmpeg/ before the SvelteKit build runs.
COPY package.json package-lock.json ./
COPY scripts ./scripts
RUN npm ci

COPY . .
RUN npm run build

FROM node:22-slim AS runtime

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts \
    && npm cache clean --force

COPY --from=builder /app/build ./build
COPY server.js isolation-headers.js ./

USER node

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then((r) => { if (!r.ok) process.exit(1); }).catch(() => process.exit(1))"]

CMD ["node", "server.js"]
