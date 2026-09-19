FROM node:24-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
# 公开的浏览器地址；不向前端传递任何后端密钥。
ARG VITE_API_URL=/api
ARG VITE_ALLOW_DOCUMENT_UPLOAD=true
ENV VITE_API_URL=$VITE_API_URL \
    VITE_ALLOW_DOCUMENT_UPLOAD=$VITE_ALLOW_DOCUMENT_UPLOAD
RUN npm run build

FROM nginx:stable-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
