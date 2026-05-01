FROM node:22-bookworm-slim AS base
WORKDIR /app

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY package*.json ./
RUN npm install

RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app

FROM base AS dev
COPY --chown=appuser:appuser . .
USER appuser
EXPOSE 5173
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:5173 || exit 1
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
