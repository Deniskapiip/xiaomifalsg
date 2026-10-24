# Bothost: единый контейнер с Mini App, API и webhook Telegram.
# Файл обязан лежать в КОРНЕ репозитория и включаться галочкой
# «Использовать собственный Dockerfile» в настройках бота Bothost.
#
# Сборка намеренно без Node: frontend/dist уже собран и лежит в репозитории.
# Так образ собирается быстро и не упирается в память сборщика Bothost.
# Если меняли интерфейс — соберите его локально (npm.cmd ci && npm.cmd run build)
# и закоммитьте frontend/dist. Вариант со сборкой фронтенда внутри платформы:
# deploy/Dockerfile.bothost-node (положить в корень под именем Dockerfile).
#
# Python 3.12 выбран потому, что все закреплённые в requirements.txt версии
# имеют готовые wheels для cp312 — установка не требует компиляции.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0

WORKDIR /srv/taoji-cargo
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY frontend/dist/ ./frontend/dist/
COPY deploy/bothost-entrypoint.sh /usr/local/bin/bothost-entrypoint
RUN chmod 755 /usr/local/bin/bothost-entrypoint \
    && mkdir -p /srv/taoji-cargo/data /srv/taoji-cargo/backups

WORKDIR /srv/taoji-cargo/backend
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/bothost-entrypoint"]
