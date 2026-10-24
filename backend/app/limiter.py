import ipaddress

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded


def request_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    # The server is bound to loopback locally. Cloudflared connects there and sets this header.
    # In production Caddy overwrites X-Forwarded-For; Uvicorn trusts only its configured proxy.
    if peer in {"127.0.0.1", "::1"} and request.headers.get("cf-connecting-ip"):
        try:
            return str(ipaddress.ip_address(request.headers["cf-connecting-ip"]))
        except ValueError:
            return peer
    return peer


def create_limiter():
    return Limiter(key_func=request_ip)


async def limit_error(_request: Request, _exc: RateLimitExceeded):
    return JSONResponse({"code": "RATE_LIMITED", "message": "Слишком много попыток. Подождите и повторите запрос."}, status_code=429)
