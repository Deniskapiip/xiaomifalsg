from enum import StrEnum
from urllib.parse import urlsplit


class Platform(StrEnum):
    taobao = "taobao"
    tmall = "tmall"
    ali1688 = "1688"
    goofish = "goofish"
    poizon = "poizon"
    unknown = "unknown"


def identify_platform(link: str) -> Platform:
    host = (urlsplit(link).hostname or "").lower().rstrip(".")
    groups = {
        Platform.taobao: ("taobao.com", "tb.cn"),
        Platform.tmall: ("tmall.com",),
        Platform.ali1688: ("1688.com",),
        Platform.goofish: ("goofish.com", "xianyu.com", "idlefish.com"),
        Platform.poizon: ("poizon.com", "dewu.com", "dewu.cn"),
    }
    for platform, domains in groups.items():
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return platform
    return Platform.unknown
