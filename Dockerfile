# Bothost: единый контейнер с Mini App, API и webhook Telegram.
# Файл обязан лежать в КОРНЕ репозитория и включаться галочкой
# «Использовать собственный Dockerfile» в настройках бота Bothost.
#
# Код приложения кладём в /srv/taoji-cargo: Bothost при запуске монтирует
# каталог /app с исходниками из Git, поэтому образ не должен рассчитывать на
# файлы внутри /app. Постоянные данные живут в /app/data (см. entrypoint).
#
# Фронтенд собирается здесь же. Если сборщик Bothost не уложится в память,
# используйте deploy/Dockerfile.bothost-prebuilt (см. deploy/BOTHOST.md):
# он берёт готовую frontend/dist и не запускает Node.
FROM node:24-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    HOST=0.0.0.0

WORKDIR /srv/taoji-cargo
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY deploy/bothost-entrypoint.sh /usr/local/bin/bothost-entrypoint
COPY --from=frontend /build/frontend/dist ./frontend/dist/
RUN chmod 755 /usr/local/bin/bothost-entrypoint \
    && mkdir -p /srv/taoji-cargo/data /srv/taoji-cargo/backups

WORKDIR /srv/taoji-cargo/backend
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/bothost-entrypoint"]
