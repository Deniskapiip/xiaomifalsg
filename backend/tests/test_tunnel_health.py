import io
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import ssl
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import check_tunnel, tunnel_health


class Response:
    def __init__(self, body, status=200):
        self.status = status
        self.body = io.BytesIO(body)
        self.closed = False

    def read(self, size):
        return self.body.read(size)

    read1 = read

    def close(self):
        self.closed = True


def install_response(monkeypatch, response):
    opener = Mock()
    opener.open.return_value = response
    factory = Mock(return_value=opener)
    monkeypatch.setattr(tunnel_health, "build_opener", factory)
    return factory, opener


def test_exact_service_success_uses_direct_transport_and_closes(monkeypatch):
    response = Response(b'{"ok":true,"service":"taoji-cargo"}')
    factory, opener = install_response(monkeypatch, response)
    result = tunnel_health.probe_health("https://current.trycloudflare.com/")
    assert result == tunnel_health.HealthResult("OK", 200)
    assert result.ok and response.closed
    proxy, redirects = factory.call_args.args
    assert proxy.proxies == {} and isinstance(redirects, tunnel_health._NoRedirect)
    request = opener.open.call_args.args[0]
    assert request.full_url == "https://current.trycloudflare.com/api/health"
    assert request.get_header("Ngrok-skip-browser-warning") == "1"
    assert opener.open.call_args.kwargs["timeout"] == 3


@pytest.mark.parametrize("body", [b'{"ok":1,"service":"taoji-cargo"}', b'{"ok":true,"service":"other"}', b'[]', b'not-json', b'x' * 8193])
def test_wrong_or_oversized_response_is_not_success(monkeypatch, body):
    response = Response(body)
    install_response(monkeypatch, response)
    assert tunnel_health.probe_health("https://test.example").code == "WRONG_SERVICE"
    assert response.closed


@pytest.mark.parametrize("status,body,code", [(200, b'<h1>Error 1033</h1>', "CLOUDFLARE_1033"), (530, b'error code: 1033', "CLOUDFLARE_1033"), (502, b'secret-body', "ORIGIN_502"), (503, b'secret-body', "HTTP_ERROR"), (302, b'', "WRONG_SERVICE")])
def test_error_classification_and_response_close(monkeypatch, status, body, code):
    if status >= 300:
        response = HTTPError("https://secret.invalid/secret", status, "private-token", {}, io.BytesIO(body))
        install_response(monkeypatch, response)[1].open.side_effect = response
    else:
        response = Response(body, status)
        install_response(monkeypatch, response)
    result = tunnel_health.probe_health("https://test.example")
    assert (result.code, result.status) == (code, status)
    assert "secret" not in result.message and "private-token" not in result.message
    assert response.closed


@pytest.mark.parametrize("exception,code", [(URLError("private-token"), "NETWORK"), (URLError(ssl.SSLError("private-token")), "TLS_ERROR"), (ssl.SSLError("private-token"), "TLS_ERROR"), (TimeoutError("private-token"), "NETWORK")])
def test_network_failures_are_static(monkeypatch, exception, code):
    factory, opener = install_response(monkeypatch, Response(b''))
    opener.open.side_effect = exception
    result = tunnel_health.probe_health("https://test.example")
    assert result.code == code and "private-token" not in result.message


@pytest.mark.parametrize("url", ["http://test.example", "https://127.0.0.1", "https://127.1", "https://0177.0.0.1", "https://0x7f.0x0.0x0.0x1", "https://[::1]", "https://user:private-token@test.example", "https://test.example/api", "https://test.example?token=private-token", "https://test.local", "https://test.example:8000", "https://test.example\n", "https://bad..example", "https://test.example\\secret"])
def test_invalid_public_urls_never_contact_network(monkeypatch, url):
    factory = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(tunnel_health, "build_opener", factory)
    assert tunnel_health.probe_health(url).code == "WRONG_SERVICE"
    factory.assert_not_called()


def test_redirect_handler_does_not_follow_private_destination():
    assert tunnel_health._NoRedirect().redirect_request(None, None, 302, "", {}, "http://127.0.0.1/private") is None


def test_caller_timeout_is_bounded_even_when_transport_stalls(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    response = Response(b'{"ok":true,"service":"taoji-cargo"}')
    _, opener = install_response(monkeypatch, response)

    def blocked(*args, **kwargs):
        entered.set()
        release.wait(1)
        return response

    opener.open.side_effect = blocked
    started = time.monotonic()
    result = tunnel_health.probe_health("https://test.example", timeout=0.02)
    elapsed = time.monotonic() - started
    release.set()
    assert entered.is_set() and result.code == "NETWORK" and elapsed < 0.3
    for _ in range(100):
        if response.closed:
            break
        time.sleep(0.001)
    assert response.closed


def test_cli_uses_case_insensitive_env_and_preserves_file(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    original = b'webapp_url=https://current.trycloudflare.com\nport=8123\nBOT_TOKEN=private-token\n'
    env.write_bytes(original)
    monkeypatch.setattr(check_tunnel, "ROOT", tmp_path)
    local = Mock(return_value=tunnel_health.HealthResult("OK", 200))
    public = Mock(return_value=tunnel_health.HealthResult("CLOUDFLARE_1033", 530))
    monkeypatch.setattr(check_tunnel, "probe_local_health", local)
    monkeypatch.setattr(check_tunnel, "probe_health", public)
    assert check_tunnel.main([]) == 1
    local.assert_called_once_with(8123)
    public.assert_called_once_with("https://current.trycloudflare.com")
    output = capsys.readouterr().out
    assert "HTTP 530" in output and "Backend работает локально" in output and "private-token" not in output
    assert env.read_bytes() == original


@pytest.mark.parametrize("contents", ["PORT=private-token\nWEBAPP_URL=https://test.example\n", "PORT=8000\nWEBAPP_URL=https://test.example/?private-token\n"])
def test_cli_invalid_configuration_never_prints_values_or_contacts_network(tmp_path, monkeypatch, capsys, contents):
    (tmp_path / ".env").write_text(contents)
    monkeypatch.setattr(check_tunnel, "ROOT", tmp_path)
    probe = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(check_tunnel, "probe_health", probe)
    monkeypatch.setattr(check_tunnel, "probe_local_health", probe)
    assert check_tunnel.main([]) == 1
    assert "private-token" not in capsys.readouterr().out
    probe.assert_not_called()


def test_local_probe_uses_fixed_loopback_root(monkeypatch):
    bounded = Mock(return_value=tunnel_health.HealthResult("OK", 200))
    monkeypatch.setattr(tunnel_health, "_bounded_probe", bounded)
    assert tunnel_health.probe_local_health(8123).ok
    bounded.assert_called_once_with("http://127.0.0.1:8123", 3)


@pytest.mark.parametrize("redirect,expected", [(False, "OK"), (True, "WRONG_SERVICE")])
def test_real_http_transport_ignores_ambient_proxy_and_never_follows_redirect(monkeypatch, redirect, expected):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("ngrok-skip-browser-warning")))
            body = b'{"ok":true,"service":"taoji-cargo"}'
            self.send_response(302 if redirect else 200)
            if redirect:
                self.send_header("Location", "/must-not-follow")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()
    try:
        result = tunnel_health.probe_local_health(server.server_port)
        assert result.code == expected
        assert requests == [("/api/health", "1")]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=1)
