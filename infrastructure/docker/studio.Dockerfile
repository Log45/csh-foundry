FROM node:24-trixie-slim@sha256:54f84b4cf8432b21aaffd5d3ce8d41e12cea0d10d33c09d2f3c9879d49d6b446 AS build
WORKDIR /repo
COPY package.json package-lock.json ./
COPY packages/typescript-sdk/ ./packages/typescript-sdk/
COPY packages/react-sdk/ ./packages/react-sdk/
COPY apps/sdk-example/package.json ./apps/sdk-example/package.json
RUN npm ci --no-audit --no-fund
RUN npm run build -w @foundry/sdk
WORKDIR /repo/apps/studio
COPY apps/studio/package.json apps/studio/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/studio/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-trixie-slim@sha256:54f84b4cf8432b21aaffd5d3ce8d41e12cea0d10d33c09d2f3c9879d49d6b446 AS runtime
WORKDIR /app
RUN apt-get purge -y mount && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx /opt/yarn-* /usr/local/bin/yarn* /usr/local/bin/corepack
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000 HOME=/tmp XDG_CACHE_HOME=/tmp
COPY --from=build --chown=node:node /repo/apps/studio/.next/standalone ./
COPY --from=build --chown=node:node /repo/apps/studio/.next/static ./.next/static
COPY --from=build --chown=node:node /repo/apps/studio/public ./public
COPY --chown=node:node infrastructure/docker/studio-entry.mjs ./
RUN rm -rf /app/.next/cache && ln -s /tmp/next-cache /app/.next/cache
USER 1000:1000
EXPOSE 3000
CMD ["node", "studio-entry.mjs"]
