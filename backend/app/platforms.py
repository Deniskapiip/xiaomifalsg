from enum import StrEnum
from urllib.parse import urlsplit


class Platform(StrEnum):
    taobao = "taobao"
    tmall = "tmall"
    ali1688 = "1688"
    goofish = "goofish"
    poizon = "poizon"
    pinduoduo = "pinduoduo"
    unknown = "unknown"


def identify_platform(link: str) -> Platform:
    host = (urlsplit(link).hostname or "").lower().rstrip(".")
    # m.tb.cn — короткие ссылки Xianyu/Goofish (подтверждено владельцем);
    # e.tb.cn и tb.cn остаются Taobao.
    if host == "m.tb.cn":
        return Platform.goofish
    groups = {
        Platform.taobao: ("taobao.com", "tb.cn"),
        Platform.tmall: ("tmall.com",),
        Platform.ali1688: ("1688.com",),
        Platform.goofish: ("goofish.com", "goofish.cn", "xianyu.com", "idlefish.com"),
        Platform.poizon: ("poizon.com", "poizon.cn", "dewu.com", "dewu.cn", "dw4.co", "dw4.cn"),
        Platform.pinduoduo: ("pinduoduo.com", "pinduoduo.cn", "yangkeduo.com"),
    }
    for platform, domains in groups.items():
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return platform
    return Platform.unknown
