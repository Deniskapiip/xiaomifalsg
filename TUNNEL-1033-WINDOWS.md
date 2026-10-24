# Ошибка Cloudflare 1033 на Windows

**1033 означает: Cloudflare не находит подключённый туннель для этого адреса.** При ошибке 502 туннель подключён, но не может обратиться к локальному backend. Старая строка `Registered tunnel connection` и работающий процесс cloudflared ещё не подтверждают, что связь сохранилась.

## Проверка текущего запуска

Оставьте окно `start.bat` открытым. Во втором PowerShell выполните:

```powershell
cd G:\taoji-cargo
.\.venv\Scripts\python.exe scripts\check_tunnel.py
```

Проверка читает текущий адрес из `.env`, проверяет локальный и публичный `/api/health` и ничего не изменяет. Если локальный ответ исправен, а публичный адрес возвращает 1033, проверять нужно соединение cloudflared с Cloudflare. Если оба ответа исправны, закройте старую Mini App и откройте новую кнопку из ответа бота на `/start`.

## Обновлённый запуск

Остановите старый запуск через Ctrl+C. Распакуйте архив обновления в `G:\` с заменой исходников. Сохраните свои `.env`, `.venv`, `data` и `backups`.

```powershell
cd G:\taoji-cargo
.\start.bat --tunnel-protocol auto
```

`auto` пробует QUIC и при невозможности UDP переходит на HTTP/2. Также доступны `--tunnel-protocol quic` и `--tunnel-protocol http2`; обычный `start.bat` использует HTTP/2.

Теперь launcher проверяет публичный `/api/health` до строки «Готово», повторяя запросы до 30 секунд. При неудаче он останавливает созданные им backend и туннель. Успешная проверка подтверждает доступность в этот момент; окно запуска и интернет должны оставаться включёнными.

Cloudflare использует порт 7844: QUIC — UDP, HTTP/2 — TCP. Если QUIC не соединяется и HTTP/2 тоже получает таймаут, повторные перезапуски не устраняют блокировку порта. Проверьте маршрут Happ или используйте ngrok ниже. Конкретная конфигурация Happ и соединение с вашего Windows-компьютера здесь не проверены. Прямой маршрут cloudflared подходит только если ваш провайдер разрешает это соединение.

Launcher выводит безопасную категорию ошибки без секретов:

| Категория | Что проверять |
| --- | --- |
| `DNS` | Разрешение адресов Cloudflare, DNS в Happ и Windows |
| `TCP_TIMEOUT` | Исходящее соединение TCP 7844, маршрут VPN и firewall |
| `QUIC_TIMEOUT` | Исходящее соединение UDP 7844; попробовать HTTP/2 |
| `TLS` | TLS-соединение; перехват HTTPS, сертификаты, маршрут |
| `RECONNECTING` | Соединение потеряно и cloudflared переподключается; причина требует дальнейшей проверки |

Анонимный адрес `trycloudflare.com` не требует аккаунта Cloudflare. Dashboard и `cloudflared tunnel list` не нужны для этой проверки.

## Резервный туннель ngrok

ngrok подключается к своей сети через исходящий TLS-порт 443. Это другой способ связи, который можно проверить, если Cloudflare недоступен.

1. Остановите старый `start.bat` через Ctrl+C.
2. Создайте бесплатный аккаунт [ngrok](https://dashboard.ngrok.com/signup). Возьмите **Your Authtoken** в [личном кабинете](https://dashboard.ngrok.com/get-started/your-authtoken).
3. Установите клиент:

   ```powershell
   winget install ngrok -s msstore
   ```

4. Откройте новое окно PowerShell и запустите:

   ```powershell
   cd G:\taoji-cargo
   .\.venv\Scripts\python.exe scripts\ngrok_tunnel.py
   ```

   Скрипт скрыто запросит authtoken, если `NGROK_AUTHTOKEN` ещё не задан в `.env`. Возьмите HTTPS-адрес из строки Forwarding и оставьте окно открытым.

5. Во втором окне выполните, заменив весь пример фактическим HTTPS-адресом ngrok:

   ```powershell
   cd G:\taoji-cargo
   .\.venv\Scripts\python.exe scripts\dev.py --url https://ВАШ-ФАКТИЧЕСКИЙ-АДРЕС.ngrok-free.app
   ```

   Дождитесь «Готово», закройте старую Mini App и откройте новую кнопку через `/start`. Оба окна должны оставаться открытыми; для остановки нажмите Ctrl+C в каждом.

Бесплатный ngrok может показать страницу **Visit Site** при первом открытии HTML в Mini App. Нажмите её, чтобы перейти в приложение. Заголовок `ngrok-skip-browser-warning` помогает программным API-запросам, но не убирает предупреждение при первоначальном открытии HTML в Telegram WebView. У бесплатного тарифа есть лимиты; он подходит для тестирования.

## Если нужны исходные сообщения cloudflared

Остановите `start.bat`. В первом PowerShell создайте отдельный пустой config и запустите туннель в видимом окне:

```powershell
$taojiTunnelConfig = Join-Path $env:TEMP 'taoji-cloudflared-test.yml'
'{}' | Set-Content -Path $taojiTunnelConfig -Encoding ascii
Get-ChildItem Env:TUNNEL_* | Remove-Item
cloudflared tunnel --config $taojiTunnelConfig --no-autoupdate --url http://127.0.0.1:8000 --protocol http2 --loglevel info
```

Строка `Remove-Item` убирает параметры прежних именованных туннелей только из окружения этого окна; `.env` не изменяется. Во втором окне запустите `scripts\dev.py --url` с новым HTTPS-адресом, выданным этим туннелем. Первое окно показывает переподключения и сетевые ошибки. До запуска backend возможен ответ 502. Если в `.env` выбран другой `PORT`, замените `8000` в команде тем же портом.

Официальные инструкции: [Cloudflare: 1033 и ошибки соединения](https://developers.cloudflare.com/tunnel/troubleshooting/), [установка ngrok на Windows](https://ngrok.com/download/windows), [сеть ngrok](https://ngrok.com/docs/gateway/agent/connectivity), [ограничения бесплатного ngrok](https://ngrok.com/docs/pricing-limits/free-plan-limits).
