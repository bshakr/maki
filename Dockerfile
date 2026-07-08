# Stage 1 — build the React/Vite SPA
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2 — python runtime serving API + SPA
FROM python:3.11.12-slim
RUN useradd --create-home maki
WORKDIR /app
COPY backend/requirements.lock.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock.txt
COPY backend/src ./src
COPY --from=frontend-build /build/dist ./static
ENV STATIC_DIR=/app/static
ENV PYTHONPATH=/app/src
USER maki
EXPOSE 8787
# Inside a container maki must bind 0.0.0.0 (binding 127.0.0.1 here would make the mapped port
# unreachable even with -p), so the bind guard's network opt-in is set deliberately. The real
# exposure control is the HOST publish scope — publish to loopback only: `-p 127.0.0.1:8787:8787`.
# maki has no auth unless MAKI_AUTH_TOKEN is set; keep it off the public internet regardless.
ENV MAKI_ALLOW_NETWORK_BIND=1 MAKI_HOST=0.0.0.0 MAKI_PORT=8787
ENTRYPOINT ["python", "-m", "maki.server"]
