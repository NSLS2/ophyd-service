FROM node:20-alpine

WORKDIR /app

# Install deps first so npm install is cached across source edits.
COPY package.json package-lock.json* ./
RUN npm install --include=dev

# Copy the rest of the source. In docker-compose the src/public/index/vite.config
# are bind-mounted on top of these for hot reload, but we COPY them here so
# `docker build` produces a self-contained image usable outside compose.
COPY . .

EXPOSE 5173

# Runs codegen against the shared-schema volume mount, then starts vite bound
# to all interfaces (default is 127.0.0.1 which is unreachable from outside the container).
CMD ["npm", "run", "dev:docker"]
