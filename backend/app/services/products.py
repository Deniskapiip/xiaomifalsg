"""Optional product metadata. Provider credentials stay on the server.

No marketplace cookies, JavaScript execution or captcha handling is used.
All outbound marketplace/image requests use allowlisted hosts and public DNS.
"""
import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import html
from html.parser import HTMLParser
import ipaddress
import json
import re
import secrets
import socket
import time
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import aiohttp

MARKET_DOMAINS = ("taobao.com", "tmall.com", "tb.cn", "goofish.com", "xianyu.com", "idlefish.com", "1688.com")
IMAGE_DOMAINS = ("alicdn.com", "taobaocdn.com")
TTL = 300
MAX_BODY = 256 * 1024
MAX_IMAGE = 3 * 1024 * 1024


class UnsafeURL(ValueError):
    pass


def allowed_host(host, domains):
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def safe_url(value, domains):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096:
        raise UnsafeURL()
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value:
        raise UnsafeURL()
    try:
        parsed = urlsplit("https:" + value if value.startswith("//") else value)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.password is not None
                or parsed.port not in {None, 80, 443} or not allowed_host(host, domains)):
            raise UnsafeURL()
        return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
    except (ValueError, TypeError):
        raise UnsafeURL() from None


def product_identity(value):
    """Only numeric product IDs from known marketplace URL shapes."""
    url = safe_url(value, MARKET_DOMAINS)
    parsed = urlsplit(url)
    host, path = parsed.hostname, parsed.path.lower()
    platform = "unknown"
    if allowed_host(host, ("goofish.com", "xianyu.com", "idlefish.com")) or (
            allowed_host(host, ("taobao.com",)) and any(x in path for x in ("idlefish", "fish-pc", "xianyu"))):
        platform = "goofish"
    elif allowed_host(host, ("1688.com",)):
        platform = "1688"
    elif allowed_host(host, ("tmall.com",)):
        platform = "tmall"
    elif allowed_host(host, ("taobao.com", "tb.cn")):
        platform = "taobao"
    query = parse_qs(parsed.query)
    product_id = next((query[key][0] for key in ("id", "itemId", "item_id", "itemid") if query.get(key)), "")
    if platform == "1688":
        match = re.fullmatch(r"/offer/(\d{1,30})\.html", parsed.path)
        product_id = match.group(1) if match else ""
    if not re.fullmatch(r"[0-9]{1,30}", product_id):
        product_id = ""
    # A short link can have an unrelated id parameter. Resolve it first.
    if allowed_host(host, ("tb.cn",)):
        product_id = ""
    return url, platform, product_id


class PublicResolver(aiohttp.abc.AbstractResolver):
    """The validated DNS records themselves are passed to TCPConnector.

    This prevents a second hostname lookup and blocks rebinding to private IPs.
    """
    def __init__(self):
        self.resolver = aiohttp.resolver.DefaultResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        records = await self.resolver.resolve(host, port, family)
        if not records or any(not ipaddress.ip_address(record["host"]).is_global for record in records):
            raise OSError("Non-public destination")
        return records

    async def close(self):
        await self.resolver.close()


async def bounded_body(response, maximum):
    if response.content_length is not None and response.content_length > maximum:
        raise ValueError("Response too large")
    body = bytearray()
    async for chunk in response.content.iter_chunked(16384):
        body.extend(chunk)
        if len(body) > maximum:
            raise ValueError("Response too large")
    return bytes(body)


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta" and values.get("http-equiv", "").lower() == "refresh":
            match = re.search(r"\burl\s*=\s*['\"]?([^'\"]+)", values.get("content", ""), re.I)
            if match:
                self.links.append(match.group(1).strip())
        elif tag == "a" and "href" in values:
            self.links.append(values["href"])
        elif tag == "link" and values.get("rel", "").lower() == "canonical" and "href" in values:
            self.links.append(values["href"])


def text(value, maximum):
    if not isinstance(value, (str, int, Decimal)):
        return ""
    value = html.unescape(re.sub(r"<[^>]*>", " ", str(value)))
    return " ".join("".join(c for c in value if ord(c) >= 32 and ord(c) != 127).split())[:maximum]


def money(value):
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        return None
    value = str(value).strip()
    if not re.fullmatch(r"\d{1,7}(?:\.\d{1,2})?", value):
        return None
    try:
        amount = Decimal(value)
        if not amount.is_finite() or not 0 < amount <= 1_000_000:
            return None
        return f"{amount:.2f}"
    except InvalidOperation:
        return None


def empty_result(url="", platform="unknown", product_id="", status="unavailable", warning="Не удалось получить товар. Заполните название и цену вручную."):
    return {"status": status, "canonical_url": url, "platform": platform, "product_id": product_id,
            "title": "", "images": [], "currency": "CNY", "price_cny": None, "variants": [], "warnings": [warning]}


def image_type(body):
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    return None


class ProductService:
    def __init__(self, settings):
        self.settings = settings
        self.products = OrderedDict()
        self.images = OrderedDict()
        self.inflight = {}
        self.semaphore = asyncio.Semaphore(4)

    @asynccontextmanager
    async def session(self, timeout):
        # This wrapper explicitly closes the caller-owned resolver as well.
        resolver = PublicResolver()
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout),
                                           connector=aiohttp.TCPConnector(resolver=resolver, limit=4),
                                           cookie_jar=aiohttp.DummyCookieJar(), trust_env=False,
                                           headers={"User-Agent": "TaojiCargo/1.0", "Accept": "application/json,text/html"}) as session:
                yield session
        finally:
            await resolver.close()

    async def resolve(self, value):
        current = safe_url(value, MARKET_DOMAINS)
        async with asyncio.timeout(8), self.session(8) as session:
            for _ in range(6):
                _, _, product_id = product_identity(current)
                if product_id:
                    return current
                async with session.get(current, allow_redirects=False) as response:
                    if response.status in {301, 302, 303, 307, 308}:
                        current = safe_url(urljoin(current, response.headers.get("Location", "")), MARKET_DOMAINS)
                        continue
                    if response.status != 200:
                        raise ValueError("Link unavailable")
                    parser = LinkParser()
                    parser.feed((await bounded_body(response, MAX_BODY)).decode("utf-8", errors="replace"))
                    for link in parser.links[:100]:
                        try:
                            candidate = safe_url(urljoin(current, link), MARKET_DOMAINS)
                            if product_identity(candidate)[2]:
                                return candidate
                        except UnsafeURL:
                            continue
                    raise ValueError("Product ID unavailable")
        raise ValueError("Too many redirects")

    async def fetch(self, platform, product_id):
        api = {"taobao": "taobao", "tmall": "taobao", "goofish": "goodfish", "1688": "1688"}[platform]
        async with self.session(10) as session:
            async with session.get(f"https://api-gw.onebound.cn/{api}/item_get/", allow_redirects=False,
                                   params={"key": self.settings.onebound_api_key, "secret": self.settings.onebound_api_secret,
                                           "num_iid": product_id, "lang": "ru", "result_type": "json", "is_promotion": "1"}) as response:
                if response.status != 200:
                    raise ValueError("Provider unavailable")
                result = json.loads(await bounded_body(response, MAX_BODY), parse_float=Decimal)
                if not isinstance(result, dict) or not isinstance(result.get("item"), dict):
                    raise ValueError("Product unavailable")
                if result.get("error_code") not in {None, "", "0", "0000", 0}:
                    raise ValueError("Provider unavailable")
                return result["item"]

    def register_image(self, value):
        try:
            url = safe_url(value, IMAGE_DOMAINS)
        except UnsafeURL:
            return None
        now = time.monotonic()
        self.prune(self.images, now)
        token = secrets.token_urlsafe(24)
        self.images[token] = (now + TTL, url)
        while len(self.images) > 512:
            self.images.popitem(last=False)
        return "/api/products/image?t=" + token

    @staticmethod
    def prune(cache, now):
        for key in list(cache):
            if cache[key][0] <= now:
                del cache[key]

    def normalize(self, item, url, platform, product_id):
        result = empty_result(url, platform, product_id, "ok")
        result["warnings"] = []
        result["title"] = text(item.get("title"), 300)
        currency = str(item.get("currency") or item.get("currency_code") or "CNY").upper().strip()
        cny = currency in {"CNY", "RMB", "CN¥", "¥", "￥"}
        if not cny:
            result["warnings"].append("Цена товара указана не в юанях. Укажите цену в CNY вручную.")
        skus = item.get("skus", {})
        rows = skus.get("sku", []) if isinstance(skus, dict) else []
        seen = set()
        if isinstance(rows, list):
            for row in rows[:256]:
                if not isinstance(row, dict) or str(row.get("quantity", "1")) == "0":
                    continue
                sku_id = text(row.get("sku_id"), 128)
                if not sku_id or sku_id in seen:
                    continue
                seen.add(sku_id)
                label = text(row.get("properties_name") or row.get("properties") or sku_id, 160)
                result["variants"].append({"id": sku_id, "label": label, "price_cny": money(row.get("price")) if cny else None})
                if len(result["variants"]) >= 60:
                    break
        prices = {row["price_cny"] for row in result["variants"]}
        if result["variants"]:
            if len(prices) == 1 and None not in prices and len(rows) <= 60:
                result["price_cny"] = next(iter(prices))
            else:
                result["warnings"].append("Выберите вариант товара и проверьте его цену перед расчётом.")
        elif cny:
            result["price_cny"] = money(item.get("promotion_price")) or money(item.get("price"))
        raw_images = [item.get("pic_url")]
        item_images = item.get("item_imgs", [])
        if isinstance(item_images, dict):
            item_images = item_images.get("item_img", [])
        if isinstance(item_images, list):
            raw_images.extend(row.get("url") if isinstance(row, dict) else row for row in item_images[:32])
        seen_urls = set()
        for image in raw_images:
            if not isinstance(image, str) or image in seen_urls:
                continue
            seen_urls.add(image)
            proxy = self.register_image(image)
            if proxy:
                result["images"].append(proxy)
            if len(result["images"]) >= 8:
                break
        if not result["title"] and result["price_cny"] is None and not result["variants"]:
            return empty_result(url, platform, product_id)
        if result["price_cny"] is None and not result["variants"] and cny:
            result["warnings"].append("Не удалось определить точную цену. Укажите её в юанях вручную.")
        if result["price_cny"] is not None or result["variants"]:
            result["warnings"].append("Проверьте цену и выбранный вариант по ссылке продавца: скидки и условия покупки могут отличаться.")
        return result

    async def preview(self, value):
        try:
            url, platform, product_id = product_identity(value)
        except UnsafeURL:
            return empty_result(warning="Нужна ссылка на товар Taobao, Tmall, 1688 или Goofish.")
        if not self.settings.onebound_api_key or not self.settings.onebound_api_secret:
            return empty_result(url, platform, product_id, "not_configured",
                                "Автозаполнение ещё не подключено. Название и цену пока можно указать вручную.")
        now = time.monotonic()
        self.prune(self.products, now)
        if url in self.products:
            return deepcopy(self.products[url][1])
        if url not in self.inflight:
            if len(self.inflight) >= 64:
                return empty_result(url, platform, product_id, warning="Загрузка товаров занята. Повторите попытку немного позже.")
            task = asyncio.create_task(self.load_preview(url, platform, product_id))
            self.inflight[url] = task
            def completed(done):
                if self.inflight.get(url) is done:
                    self.inflight.pop(url, None)
            task.add_done_callback(completed)
        return deepcopy(await asyncio.shield(self.inflight[url]))

    async def load_preview(self, url, platform, product_id):
        async with self.semaphore:
            self.prune(self.products, time.monotonic())
            if url in self.products:
                return deepcopy(self.products[url][1])
            try:
                original = url
                if not product_id:
                    url = await self.resolve(url)
                    url, platform, product_id = product_identity(url)
                if not product_id:
                    return empty_result(url, platform, product_id)
                item = await self.fetch(platform, product_id)
                result = self.normalize(item, url, platform, product_id)
                self.products[original] = (time.monotonic() + TTL, deepcopy(result))
                while len(self.products) > 64:
                    self.products.popitem(last=False)
                return result
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError, KeyError, TypeError, RecursionError):
                return empty_result(url, platform, product_id)

    async def image(self, token):
        self.prune(self.images, time.monotonic())
        if not re.fullmatch(r"[A-Za-z0-9_-]{32}", token) or token not in self.images:
            return None
        url = self.images[token][1]
        async with self.semaphore:
            try:
                async with self.session(5) as session:
                    async with session.get(url, allow_redirects=False, headers={"Accept": "image/jpeg,image/png,image/webp,image/gif"}) as response:
                        if response.status != 200:
                            return None
                        body = await bounded_body(response, MAX_IMAGE)
                        media = image_type(body)
                        return (body, media) if media else None
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
                return None
