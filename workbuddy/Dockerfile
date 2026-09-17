# WorkBuddy 前端：构建阶段（Vite 打包，VITE_* 经 build args 注入）
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY . .
ARG VITE_GW_BASE=http://localhost:8000
ARG VITE_HUB_BASE=http://localhost:8081
ENV VITE_GW_BASE=$VITE_GW_BASE VITE_HUB_BASE=$VITE_HUB_BASE
RUN npm run build

# 运行阶段：nginx 托管静态产物（SPA 回退到 index.html）
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
