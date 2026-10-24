"""TCP-алиасы для хостинга Bothost.

Bothost проксирует домен на «внутренний порт», который задаётся в панели,
но не всегда передаёт его приложению в переменной PORT. Приложение слушает
один порт, а этот модуль открывает остальные типовые порты и прозрачно
перенаправляет TCP-соединения на основной порт.

Ничего не пишет на диск, не требует зависимостей и почти не потребляет память.
Для HTTP и webhook Telegram этого достаточно: WebSocket Mini App не использует.
"""

import asyncio
import os
import sys


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        writer.close()


async def _handle(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter, target_port: int) -> None:
    try:
        server_reader, server_writer = await asyncio.open_connection("127.0.0.1", target_port)
    except OSError:
        client_writer.close()
        return
    await asyncio.gather(_pipe(client_reader, server_writer), _pipe(server_reader, client_writer))


async def main() -> None:
    target_port = int(os.environ.get("PORT", "3000"))
    candidates = [3000, 8000, 8080, 5000]
    servers = []
    for port in candidates:
        if port == target_port:
            continue
        try:
            servers.append(await asyncio.start_server(
                lambda reader, writer, port=port: _handle(reader, writer, target_port), "0.0.0.0", port))
        except OSError:
            continue
    if not servers:
        print("[port-alias] no extra ports available", flush=True)
        return
    bound = ", ".join(str(server.sockets[0].getsockname()[1]) for server in servers if server.sockets)
    print(f"[port-alias] forwarding {bound} -> 127.0.0.1:{target_port}", flush=True)
    await asyncio.gather(*(server.serve_forever() for server in servers))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
