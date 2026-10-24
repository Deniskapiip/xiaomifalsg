FROM node:24-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# tsc проверяет тесты, а pricing.test.ts импортирует ../../../shared/pricing_cases.json.
COPY shared/ /build/shared/
RUN npm run build

FROM python:3.13-slim-bookworm AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1
WORKDIR /srv/taoji-cargo
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && groupadd --gid 10001 taoji \
    && useradd --uid 10001 --gid taoji --no-create-home taoji
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY --from=frontend /build/frontend/dist ./frontend/dist/
USER 10001:10001
WORKDIR /srv/taoji-cargo/backend
EXPOSE 8000
CMD ["python", "-m", "app.main"]
