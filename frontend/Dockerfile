FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install

COPY . .
# We build with VITE_API_URL empty so requests go to the same origin, 
# relying on a Kubernetes Ingress to route /api traffic to the backend.
RUN VITE_API_URL="" npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html

# A basic config to fall back to index.html for SPA routing
RUN printf 'server {\n\
    listen 80;\n\
    location / {\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    try_files $uri $uri/ /index.html;\n\
    }\n\
    }\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
