# ============================================================
# Frontend Dockerfile — OCOP-RAG (React + Vite)
# ============================================================
# Two-layer image construction:
# Builder: Install deps + build production bundle
# Static server: Serve static files with nginx
# ============================================================

# --------------- Builder: Build ---------------
FROM node:22-alpine AS build

WORKDIR /app

# Copy package files first for dependency caching
COPY package.json package-lock.json ./

RUN npm ci --ignore-scripts

# Copy source code and build
COPY . .

# Build-time environment variable for API URL
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# --------------- Static server: Serve ---------------
FROM nginx:alpine AS production

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets from build stage
COPY --from=build /app/dist /usr/share/nginx/html

# Expose port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
