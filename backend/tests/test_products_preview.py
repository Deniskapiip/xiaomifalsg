import asyncio
from types import SimpleNamespace

import aiohttp
import pytest

from app.services import products
from app.services.products import ProductService, PublicResolver, UnsafeURL, bounded_body, image_type, money, product_identity, safe_url


@pytest.fixture
def service():
    return ProductService(SimpleNamespace(onebound_api_key="private-test-key", onebound_api_secret="private-test-secret"))


@pytest.mark.parametrize("url,platform,product_id", [
    ("https://item.taobao.com/item.htm?id=123", "taobao", "123"),
    ("http://detail.tmall.com/item.htm?id=456", "tmall", "456"),
    ("https://www.goofish.com/item?id=789", "goofish", "789"),
    ("https://h5.m.goofish.com/item?itemId=789", "goofish", "789"),
    ("https://market.m.taobao.com/app/idleFish-F2e/fish-pc/web/detail.html?id=789", "goofish", "789"),
    ("https://detail.1688.com/offer/123456.html", "1688", "123456"),
    ("https://m.tb.cn/h.xyz?id=123", "taobao", ""),
])
def test_recognized_product_links(url, platform, product_id):
    canonical, found_platform, found_id = product_identity(url)
    assert canonical.startswith("https://")
    assert (found_platform, found_id) == (platform, product_id)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/private", "https://taobao.com.evil.invalid/?id=123", "https://eviltaobao.com/?id=123",
    "https://user:password@item.taobao.com/?id=123", "https://item.taobao.com:8080/?id=123",
    "file:///etc/passwd", "https://item.taobao.com\\@127.0.0.1/?id=123", "https://item.taobao.com/\nfoo",
    "https://item.taobao.com./?id=123", "https://[::1]/?id=123", "javascript:alert(1)",
])
def test_url_allowlist_blocks_private_and_ambiguous_urls(url):
    with pytest.raises(UnsafeURL):
        safe_url(url, products.MARKET_DOMAINS)


@pytest.mark.parametrize("value,expected", [
    ("13.5", "13.50"), ("1000000.00", "1000000.00"), (0, None), ("0.00", None),
    ("-10", None), ("13.501", None), ("10-20", None), ("NaN", None), ("1e5", None),
    ("1000000.01", None), (True, None), ("$15", None),
])
def test_prices_are_positive_exact_bounded_decimal(value, expected):
    assert money(value) == expected


async def test_preview_requires_authentication(client):
    response = await client.post("/api/products/preview", json={"url": "https://item.taobao.com/item.htm?id=123"})
    assert response.status_code == 401


async def test_no_keys_manual_fallback_never_makes_network_request(client, auth_headers, monkeypatch):
    async def forbidden(*args):
        raise AssertionError("Unconfigured preview must not make a network request")
    monkeypatch.setattr(ProductService, "resolve", forbidden)
    monkeypatch.setattr(ProductService, "fetch", forbidden)
    response = await client.post("/api/products/preview", json={"url": "https://m.tb.cn/h.link"}, headers=await auth_headers())
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "not_configured"
    assert result["title"] == "" and result["price_cny"] is None
    assert result["warnings"]


async def test_provider_response_title_images_price_cache(service, monkeypatch):
    calls = []
    async def fake_provider(platform, product_id):
        calls.append((platform, product_id))
        return {"title": "<b>Huawei</b> Mate Xs 2", "price": "99", "promotion_price": "88.5",
                "pic_url": "//img.alicdn.com/example.jpg", "item_imgs": [{"url": "https://evil.invalid/image.svg"}]}
    monkeypatch.setattr(service, "fetch", fake_provider)
    result = await service.preview("https://www.goofish.com/item?id=123")
    assert result["status"] == "ok"
    assert result["title"] == "Huawei Mate Xs 2"
    assert result["price_cny"] == "88.50" and result["currency"] == "CNY"
    assert len(result["images"]) == 1 and result["images"][0].startswith("/api/products/image?t=")
    assert "alicdn" not in result["images"][0]
    again = await service.preview("https://www.goofish.com/item?id=123")
    assert again == result and calls == [("goofish", "123")]
    result["images"].clear()
    assert (await service.preview("https://www.goofish.com/item?id=123"))["images"]


async def test_concurrent_identical_previews_only_bill_one_provider_call(service, monkeypatch):
    calls = []
    entered = asyncio.Event()
    finish = asyncio.Event()
    async def fake_provider(*args):
        calls.append(args)
        entered.set()
        await finish.wait()
        return {"title": "Item", "price": "20"}
    monkeypatch.setattr(service, "fetch", fake_provider)
    first = asyncio.create_task(service.preview("https://item.taobao.com/item.htm?id=123"))
    await entered.wait()
    remaining = [asyncio.create_task(service.preview("https://item.taobao.com/item.htm?id=123")) for _ in range(6)]
    finish.set()
    results = await asyncio.gather(first, *remaining)
    assert len(calls) == 1 and all(result["price_cny"] == "20.00" for result in results)


async def test_full_product_cache_keeps_all_registered_images_alive(service, monkeypatch):
    async def fake_provider(platform, product_id):
        return {"title": "Item", "price": "20", "item_imgs": [
            {"url": f"https://img.alicdn.com/{product_id}/{i}.jpg"} for i in range(8)]}
    monkeypatch.setattr(service, "fetch", fake_provider)
    for i in range(70):
        await service.preview(f"https://item.taobao.com/item.htm?id={i}")
    assert len(service.products) == 64 and len(service.images) == 512
    for entry in service.products.values():
        assert all(url.split("=", 1)[1] in service.images for url in entry[1]["images"])


def test_different_sku_prices_require_selection(service):
    result = service.normalize({"title": "Shoes", "price": "1", "skus": {"sku": [
        {"sku_id": "small", "properties_name": "Size:Small", "price": "20", "quantity": "1"},
        {"sku_id": "large", "properties_name": "Size:Large", "price": "30", "quantity": "1"},
        {"sku_id": "sold", "properties_name": "Sold out", "price": "1", "quantity": "0"},
    ]}}, "https://item.taobao.com/item.htm?id=123", "taobao", "123")
    assert result["price_cny"] is None
    assert [row["price_cny"] for row in result["variants"]] == ["20.00", "30.00"]
    assert result["warnings"]


def test_explicit_non_cny_never_used_for_calculation(service):
    result = service.normalize({"title": "Item", "currency": "USD", "price": "25",
                                "skus": {"sku": [{"sku_id": "1", "price": "25"}]}},
                               "https://item.taobao.com/item.htm?id=1", "taobao", "1")
    assert result["price_cny"] is None
    assert result["variants"][0]["price_cny"] is None
    assert result["warnings"]


def test_variants_images_and_cache_are_bounded(service):
    rows = [{"sku_id": str(i), "properties_name": "x" * 1000, "price": "10"} for i in range(100)]
    result = service.normalize({"title": "x" * 500, "skus": {"sku": rows}}, "https://item.taobao.com/?id=1", "taobao", "1")
    assert len(result["variants"]) == 60 and len(result["title"]) == 300
    assert max(len(row["label"]) for row in result["variants"]) == 160
    assert result["price_cny"] is None
    for i in range(520):
        service.register_image(f"https://img.alicdn.com/{i}.jpg")
    assert len(service.images) == 512


async def test_provider_errors_do_not_leak_credentials(service, monkeypatch):
    async def failure(*args):
        raise aiohttp.ClientConnectionError("URL contains private-test-key and private-test-secret")
    monkeypatch.setattr(service, "fetch", failure)
    result = await service.preview("https://item.taobao.com/item.htm?id=123")
    assert result["status"] == "unavailable"
    assert "private-test" not in str(result)


async def test_private_dns_blocks_before_connection():
    resolver = PublicResolver()
    class PrivateDNS:
        async def resolve(self, *args):
            return [{"host": "127.0.0.1"}, {"host": "1.1.1.1"}]
        async def close(self):
            pass
    await resolver.resolver.close()
    resolver.resolver = PrivateDNS()
    with pytest.raises(OSError, match="Non-public"):
        await resolver.resolve("item.taobao.com", 443)
    await resolver.close()


async def test_owned_resolver_is_closed_even_when_session_body_fails(service, monkeypatch):
    closed = []
    class TrackingResolver(PublicResolver):
        async def close(self):
            closed.append(True)
            await super().close()
    monkeypatch.setattr(products, "PublicResolver", TrackingResolver)
    with pytest.raises(ValueError):
        async with service.session(1) as session:
            assert session.trust_env is False
            raise ValueError("Download failed")
    assert closed == [True]


class FakeContent:
    def __init__(self, body):
        self.body = body
    async def iter_chunked(self, maximum):
        for start in range(0, len(self.body), maximum):
            yield self.body[start:start + maximum]


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None):
        self.status, self.headers = status, headers or {}
        self.content_length = None
        self.content = FakeContent(body)
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses.pop(0)


async def test_short_link_can_follow_allowed_redirect_to_product(service, monkeypatch):
    session = FakeSession([FakeResponse(302, headers={"Location": "https://www.goofish.com/item?id=987"})])
    monkeypatch.setattr(service, "session", lambda timeout: session)
    assert await service.resolve("https://m.tb.cn/h.share") == "https://www.goofish.com/item?id=987"
    assert len(session.requests) == 1 and session.requests[0][1]["allow_redirects"] is False


async def test_short_link_cannot_follow_redirect_to_localhost(service, monkeypatch):
    session = FakeSession([FakeResponse(302, headers={"Location": "http://127.0.0.1/private"})])
    monkeypatch.setattr(service, "session", lambda timeout: session)
    with pytest.raises(UnsafeURL):
        await service.resolve("https://m.tb.cn/h.share")
    assert len(session.requests) == 1


async def test_short_link_simple_meta_refresh_and_html_entities(service, monkeypatch):
    response = FakeResponse(body=b'<meta http-equiv="refresh" content="0;url=https://item.taobao.com/item.htm?id=999&amp;spm=foo">')
    session = FakeSession([response])
    monkeypatch.setattr(service, "session", lambda timeout: session)
    assert (await service.resolve("https://m.tb.cn/h.share")).endswith("id=999&spm=foo")


async def test_short_link_redirect_count_is_bounded(service, monkeypatch):
    session = FakeSession([FakeResponse(302, headers={"Location": "https://m.tb.cn/h.loop"}) for _ in range(10)])
    monkeypatch.setattr(service, "session", lambda timeout: session)
    with pytest.raises(ValueError, match="Too many redirects"):
        await service.resolve("https://m.tb.cn/h.loop")
    assert len(session.requests) == 6


async def test_response_size_checked_even_without_content_length():
    with pytest.raises(ValueError, match="Response too large"):
        await bounded_body(FakeResponse(body=b"x" * 100), 99)


async def test_image_tokens_never_accept_arbitrary_url(service, monkeypatch, client):
    def forbidden(timeout):
        raise AssertionError("Unexpected image download")
    monkeypatch.setattr(service, "session", forbidden)
    assert await service.image("https://127.0.0.1/private") is None
    assert await service.image("A" * 32) is None
    response = await client.get("/api/products/image", params={"t": "https://127.0.0.1/private"})
    assert response.status_code == 404


async def test_image_fetch_only_registered_allowlisted_url_and_rejects_svg(service, monkeypatch):
    path = service.register_image("//img.alicdn.com/item.png")
    token = path.split("=", 1)[1]
    session = FakeSession([FakeResponse(body=b"\x89PNG\r\n\x1a\nimage")])
    monkeypatch.setattr(service, "session", lambda timeout: session)
    assert await service.image(token) == (b"\x89PNG\r\n\x1a\nimage", "image/png")
    assert session.requests[0][0] == "https://img.alicdn.com/item.png"
    assert session.requests[0][1]["allow_redirects"] is False
    session.responses.append(FakeResponse(body=b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'))
    assert await service.image(token) is None


async def test_expired_image_tokens_do_not_download(service, monkeypatch):
    path = service.register_image("https://img.alicdn.com/item.jpg")
    token = path.split("=", 1)[1]
    service.images[token] = (0, service.images[token][1])
    monkeypatch.setattr(service, "session", lambda timeout: pytest.fail("Expired token downloaded"))
    assert await service.image(token) is None


def test_magic_detection_rejects_html_and_svg():
    assert image_type(b"<html>error</html>") is None
    assert image_type(b"<svg onload='alert(1)'></svg>") is None
    assert image_type(b"RIFF1234WEBPdata") == "image/webp"


async def test_provider_uses_fixed_host_and_platform_mapping(service, monkeypatch):
    session = FakeSession([FakeResponse(body=b'{"error_code":"0000","item":{"title":"Test","price":"12"}}')])
    monkeypatch.setattr(service, "session", lambda timeout: session)
    assert await service.fetch("goofish", "123") == {"title": "Test", "price": "12"}
    url, kwargs = session.requests[0]
    assert url == "https://api-gw.onebound.cn/goodfish/item_get/"
    assert kwargs["params"]["num_iid"] == "123"
    assert kwargs["allow_redirects"] is False


async def test_preview_limit(client, auth_headers):
    headers = await auth_headers()
    codes = [(await client.post("/api/products/preview", json={"url": "https://item.taobao.com/item.htm?id=1"}, headers=headers)).status_code
             for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[-1] == 429


def test_config_credentials_hidden_from_repr(settings):
    settings.onebound_api_key, settings.onebound_api_secret = "private-test-key", "private-test-secret"
    assert "private-test" not in repr(settings)
