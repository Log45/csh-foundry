FROM node:24-trixie-slim AS build
WORKDIR /app
COPY apps/studio/package.json apps/studio/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/studio/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-trixie-slim AS runtime
WORKDIR /app
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx /opt/yarn-* /usr/local/bin/yarn* /usr/local/bin/corepack
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --chown=node:node infrastructure/docker/studio-entry.mjs ./
USER node
EXPOSE 3000
CMD ["node", "studio-entry.mjs"]
