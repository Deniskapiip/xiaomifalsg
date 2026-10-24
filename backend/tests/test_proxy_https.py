"""Production HTTPS check must accept requests proxied by a hosting platform."""

from types import SimpleNamespace

from starlette.requests import Request

from app.main import is_secure_request

OVER_PROXY = SimpleNamespace(trust_proxy_https=False)
TRUSTING_PROXY = SimpleNamespace(trust_proxy_https=True)


def make_request(scheme="http", client=("172.17.0.1", 50000), headers=None):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/health",
        "query_string": b"",
        "scheme": scheme,
        "client": client,
        "server": ("testserver", 80),
        "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
    }
    return Request(scope)


def test_direct_https_is_secure():
    assert is_secure_request(make_request(scheme="https", client=("8.8.8.8", 1234)), OVER_PROXY)


def test_forwarded_proto_https_is_secure():
    assert is_secure_request(make_request(client=("8.8.8.8", 1234), headers={"X-Forwarded-Proto": "https"}), OVER_PROXY)


def test_private_proxy_network_is_secure_without_headers():
    # Bothost/Caddy proxy connects from a private Docker network over plain HTTP.
    assert is_secure_request(make_request(client=("10.0.0.5", 1234)), OVER_PROXY)
    assert is_secure_request(make_request(client=("192.168.1.10", 1234)), OVER_PROXY)


def test_direct_public_http_is_not_secure():
    assert not is_secure_request(make_request(client=("8.8.8.8", 1234)), OVER_PROXY)


def test_forwarded_http_from_public_client_is_not_secure():
    assert not is_secure_request(make_request(client=("8.8.8.8", 1234), headers={"X-Forwarded-Proto": "http"}), OVER_PROXY)


def test_explicit_trust_for_platforms_that_strip_headers():
    assert is_secure_request(make_request(client=("8.8.8.8", 1234)), TRUSTING_PROXY)

