# Этап 5 — постоянный сервер

## Что мы сделали и зачем

Подготовлены Docker Compose, PostgreSQL 17 и Caddy с автоматическим HTTPS. Приложение работает одним процессом и получает обновления Telegram через webhook. Домен постоянный, ПК дома можно выключать. Сам сервер ещё не развёрнут: для этого нужны ваш VPS и домен.

Добавлены отдельная настройка .env.production, перенос проверенной SQLite-копии в пустую PostgreSQL, резервирование и обновление. Локальный Windows-запуск из этапа 4 сохраняется; проверять его дома можно по прежней инструкции.

## Как проверить

### 1. Подготовка на Windows

Распакуйте обновление в G:\ с заменой исходников G:\taoji-cargo. Сохраните .env, .venv, data и backups. Готовый frontend/dist включён. Для местной проверки:

```powershell
cd G:\taoji-cargo
.\.venv\Scripts\python.exe scripts\dev.py --local --local-role owner
```

В другом окне можно запустить тесты:

```powershell
cd G:\taoji-cargo\backend
..\.venv\Scripts\python.exe -m pytest -q
```

Для серверных настроек из корня проекта:

```powershell
cd G:\taoji-cargo
.\.venv\Scripts\python.exe scripts\setup_production.py
```

Мастер спросит домен, email для сертификатов, токен со скрытым вводом и числовые ID администраторов. Он создаёт отдельный .env.production, не меняет локальный .env и отказывается заменять уже существующий серверный файл. Пароль PostgreSQL и три разных секрета генерируются автоматически. После первого запуска БД пароль в файле сам по себе не меняет пароль существующей базы.

### 2. VPS, DNS и Docker

Подойдёт VPS Ubuntu 24.04 LTS x64 с достаточным местом для БД и копий. Нужен домен или поддомен, например cargo.your-domain.ru. У регистратора задайте A-запись на IPv4 VPS. Если задаёте AAAA, IPv6 тоже должен вести на этот сервер. На первом запуске используйте прямую DNS-запись без дополнительного CDN-прокси.

Подключитесь через SSH своим аккаунтом администратора. Сохраните доступ к SSH, затем откройте только нужные публичные порты:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable
```

Установите Docker Engine и Compose из [официальной инструкции для Ubuntu](https://docs.docker.com/engine/install/ubuntu/), раздел Install using the apt repository. Проверьте:

```bash
sudo docker --version
sudo docker compose version
```

Не открывайте порты 8000 и 5432: Compose их не публикует. Публикуются только порты Caddy. Приложение доверяет заголовкам HTTPS/IP только loopback и Caddy 172.30.0.2; Caddy заменяет входные X-Forwarded-* и удаляет чужие CF-Connecting-IP/Forwarded.

Создайте /opt/taoji-cargo и перенесите туда исходники архива. Отдельно через SSH/SCP перенесите .env.production. Его нет в публичном архиве. Сохраните права:

```bash
cd /opt/taoji-cargo
sudo chmod 600 .env.production
sudo sh deploy/compose.sh config --quiet
sudo sh deploy/compose.sh build app
sudo sh deploy/compose.sh up -d postgres caddy
```

config --quiet проверяет Compose без вывода секретов. Перед первым запуском app дождитесь рабочего сертификата Caddy на вашем домене. Пока app не запущен, HTTPS может отвечать 502; сертификат уже должен быть действительным. При необходимости смотрите журнал Caddy, не публикуя секреты и адрес webhook.

### 3. Новая установка без переноса

```bash
sudo sh deploy/compose.sh run --rm --no-deps app python -m alembic upgrade head
sudo sh deploy/compose.sh run --rm --no-deps app python -m app.seed
sudo sh deploy/compose.sh up -d --wait --wait-timeout 120 app
```

Создаются четыре пустых неактивных тарифа, стартовый курс и комиссия. Настройте настоящие условия в админке. Не включайте демо-тарифы как коммерческое предложение.

### 4. Перенос существующих заказов

Остановите локальный launcher через Ctrl+C и больше не создавайте заказы до окончания переноса. Сохраните SQLite online backup:

```powershell
cd G:\taoji-cargo
.\.venv\Scripts\python.exe scripts\backup.py
```

Выберите выданный файл из backups, перенесите на VPS в /opt/taoji-cargo/imports/source.db. Это один проверенный файл backup; обычную работающую SQLite без WAL копировать нельзя. Сохраните оригинал дома.

На VPS выполните миграции PostgreSQL, но **не seed**, и не запускайте app до импорта:

Перед переносом рабочей базы проверьте интеграционные тесты на отдельной базе taoji_integration. Эти проверки здесь не прошли на нативной PostgreSQL: в среде нет работающего Docker/PostgreSQL. Следующие команды создают и затем удаляют только тестовую базу; рабочая taoji не используется:

```bash
sudo sh deploy/compose.sh exec -T postgres createdb -U taoji taoji_integration
sudo sh deploy/compose.sh run --rm --no-deps app python -c 'import os,pytest; from sqlalchemy.engine import make_url; os.environ["TAOJI_TEST_POSTGRES_URL"]=make_url(os.environ["DATABASE_URL"]).set(database="taoji_integration").render_as_string(hide_password=False); os.environ["TAOJI_TEST_POSTGRES_DISPOSABLE"]="yes"; raise SystemExit(pytest.main(["-q","--tb=line","tests/test_postgres_import.py"]))'
sudo sh deploy/compose.sh exec -T postgres dropdb -U taoji taoji_integration
```

Ожидается 5 passed. Если тесты не прошли, не переносите рабочие данные: сохраните SQLite-копию и сначала разберите ошибку. Затем можно выполнить перенос:

```bash
cd /opt/taoji-cargo
sudo sh deploy/compose.sh run --rm --no-deps app python -m alembic upgrade head
sudo chown 10001:10001 imports imports/source.db
sudo chmod 700 imports
sudo chmod 600 imports/source.db
sudo sh deploy/compose.sh run --rm --no-deps -v /opt/taoji-cargo/imports:/imports:ro app python /srv/taoji-cargo/scripts/sqlite_to_postgres.py --source /imports/source.db
sudo sh deploy/compose.sh up -d --wait --wait-timeout 120 app
```

Копию читает только UID 10001 непривилегированного app-контейнера и администратор сервера. После переноса сохраните её в своём закрытом хранилище; исходный файл дома остаётся нетронутым.

Импорт сверяет целостность, внешние ключи и ревизии, сохраняет ID, Decimal, UTC-даты, тарифы, настройки, заказы и историю. Вставки выполняются одной транзакцией; непустая целевая БД отвергается без объединения данных. PostgreSQL sequences выставляются после переноса, чтобы новые номера не конфликтовали.

Старая неотправленная очередь приостанавливается. Сначала проверьте бизнес-заказы и журнал; если нужно возобновить все эти сообщения, выполните явную команду:

```bash
sudo sh deploy/compose.sh run --rm --no-deps app python /srv/taoji-cargo/scripts/resume_import_notifications.py --confirm-send-old-notifications
```

Эта команда разрешит боту отправлять старые сообщения тем, у кого есть доступ. Можно оставить очередь приостановленной. Новые заказы и новые смены статусов уведомляются штатно. Не запускайте домашний polling-бот одновременно с серверным webhook на том же токене.

### 5. Проверка после запуска

```bash
sudo sh deploy/compose.sh ps
curl --fail https://ВАШ-ДОМЕН/api/health
```

Ожидаются healthy у app/postgres и JSON с ok=true. App сам задаёт webhook с секретным путём и заголовком, команды и кнопку меню на постоянный домен. В Telegram заново нажмите /start и откройте приложение из меню. Проверьте четыре аккаунта и сценарии [ACCEPTANCE-TELEGRAM.md](ACCEPTANCE-TELEGRAM.md), включая новые статусы и светлую/тёмную тему.

Для внешнего контроля доступности можно проверять HTTPS /api/health сервисом мониторинга, например [UptimeRobot](https://uptimerobot.com/). Его текущий Free позиционируется для hobby/non-profit проектов: условия для вашего бизнеса сверяйте с [тарифом](https://uptimerobot.com/pricing/). Сервис здесь не подключён. Мониторинг проверяет доступность API и БД; фактическую доставку ботом проверяйте по журналу и контрольному заказу. Секретный webhook URL не передавайте сервису мониторинга.

### 6. PostgreSQL-копии

```bash
cd /opt/taoji-cargo
sudo sh deploy/backup-postgres.sh
```

Скрипт создаёт pg_dump custom format, проверяет каталог pg_restore и публикует готовый файл в backups/postgres. Остаются 14 копий только его строгого формата. Ошибка дампа не удаляет старые копии. Копия на VPS не защищает от потери VPS — переносите её в своё отдельное закрытое хранилище.

Для ежедневного расписания откройте sudo crontab -e и добавьте строку (время по часовому поясу сервера):

```cron
15 2 * * * /bin/sh /opt/taoji-cargo/deploy/backup-postgres.sh >> /var/log/taoji-backup.log 2>&1
```

Пример с 02:15 выполняется каждый день; .env.production и дампы не публикуйте. Регулярно проверяйте журнал и тестируйте восстановление в отдельной пустой базе.

### 7. Восстановление

Остановите app, сделайте копию текущей PostgreSQL, выберите проверенный dump. Предпочтительный путь — новая отдельная база и проверка в ней. Для аварийного восстановления на месте команда ниже перезаписывает существующие таблицы; используйте её только с выбранной копией и остановленным app:

```bash
sudo sh deploy/compose.sh stop app
sudo sh deploy/backup-postgres.sh
sudo sh deploy/compose.sh exec -T postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-acl --single-transaction' < backups/postgres/ВЫБРАННАЯ-КОПИЯ.dump
sudo sh deploy/compose.sh up -d --wait --wait-timeout 120 app
```

Поздние изменения исчезнут из восстановленной базы; они останутся в дополнительной копии, которую вы сделали перед восстановлением. Ревизия БД и исходники приложения должны соответствовать выбранной версии.

### 8. Обновление

Сохраните предыдущую версию исходников и образа. Замените исходники проверенным обновлением, сохранив .env.production, volumes, imports и backups. Для собственного Git-репозитория сначала git pull --ff-only; адрес репозитория проектом не задан.

```bash
cd /opt/taoji-cargo
sudo sh deploy/update.sh
```

Скрипт резервирует БД, собирает новый app, останавливает старый app, применяет миграции и ждёт готовности новой версии. На время остановки возможен короткий 502. Если миграция или запуск завершились ошибкой, не выполняйте downgrade и не удаляйте volumes: сверяйтесь с сохранённой версией и копией. Автоматический откат схемы не выполняется.

## Что может пойти не так и что делать

| Симптом | Проверка |
|---|---|
| Сертификат не получается | A/AAAA, прямой DNS, доступные 80/443, журнал Caddy и правильный DOMAIN |
| App unhealthy | PostgreSQL, миграция и seed/импорт, токен, webhook-секреты, HTTPS; журнал app без публикации секретов |
| Все запросы получают HTTPS_REQUIRED | Точный IP Caddy и FORWARDED_ALLOW_IPS должны совпадать; не расширяйте доверие до * |
| Сеть Docker пересекается с другой | Измените подсеть 172.30.0.0/24, адрес Caddy и список доверенных IP согласованно |
| Импорт отказывается работать | Цель должна быть пустой и мигрированной; seed или уже существующие заказы не удаляются автоматически |
| Бот после переноса не отправляет старую очередь | Это состояние paused_migration; возобновляйте только явной командой после проверки |
| PostgreSQL требует пароль после редактирования файла | Существующий volume не меняет пароль при смене POSTGRES_PASSWORD; восстановите согласованную конфигурацию |
| Ошибка обновления | Сохраните копии, прочтите журнал; возврат к старому образу требует совместимой схемы |

Никогда не используйте docker compose down -v как обычную остановку: -v удаляет тома, включая рабочую PostgreSQL и сертификаты. Остановка приложения — compose.sh stop app; остановка всего проекта без удаления данных — compose.sh down.

Официальные источники: [Docker Compose](https://docs.docker.com/reference/compose-file/services/), [Caddy reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [PostgreSQL pg_dump](https://www.postgresql.org/docs/current/app-pgdump.html).
