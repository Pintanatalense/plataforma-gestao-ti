# =============================================================================
# Nginx — constrói o frontend Angular e serve como arquivos estáticos
# Contexto de build: raiz do repositório (ver docker-compose.yml)
# =============================================================================

FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx/app-locations.conf /etc/nginx/snippets/app-locations.conf
COPY --from=frontend /build/dist/plataforma-gestao-ti/browser /usr/share/nginx/html
EXPOSE 80 443
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -q --spider http://127.0.0.1/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
