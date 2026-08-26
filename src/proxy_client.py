"""Client for the proxyxoay.shop rotating-proxy API.

API contract (from the vendor docs)::

    GET https://proxyxoay.shop/api/get.php?key=<key>&nhamang=random&tinhthanh=0&whitelist=

    {
      "status": 100,
      "message": "proxy nay se die sau 1777s",
      "proxyhttp":   "42.117.243.215:10836::",
      "proxysocks5": "42.117.243.215:30836::",
      "Nha Mang": "fpt",
      "Vi Tri": "HaNoi1",
      "Token expiration date": "22:52 19-02-2025"
    }

``status == 100`` means success; anything else is an error carried in ``message``
(most often a rotation cooldown such as "vui long doi 45s").  Endpoints come back
as ``ip:port:user:pass`` with the credential halves empty when the key is bound to
an IP whitelist instead.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

API_URL = "https://proxyxoay.shop/api/get.php"
STATUS_OK = 100

# Substrings that mean "retrying will not help" -- bad or exhausted key.
_FATAL_HINTS = (
    "key khong ton tai",
    "key không tồn tại",
    "key sai",
    "sai key",
    "invalid key",
    "het han",
    "hết hạn",
    "expired",
    "khong du tien",
    "không đủ tiền",
)

_WAIT_RE = re.compile(r"(\d+)\s*(?:s\b|giay|giây)", re.IGNORECASE)


class ProxyApiError(RuntimeError):
    """The API was reachable but did not hand back a usable proxy."""

    def __init__(self, status: int, message: str, fatal: bool = False) -> None:
        super().__init__(f"status={status}: {message}")
        self.status = status
        self.message = message
        self.fatal = fatal

    @property
    def retry_after(self) -> int | None:
        """Seconds the API asked us to wait, if it said so."""
        found = _WAIT_RE.search(self.message)
        return int(found.group(1)) if found else None


@dataclass(frozen=True)
class Proxy:
    host: str
    port: int
    username: str = ""
    password: str = ""
    protocol: str = "http"
    carrier: str = ""
    location: str = ""
    lifetime: str = ""
    source: str = "rotating"   # "rotating" | "static"
    label: str = ""            # human tag for static entries

    @property
    def has_auth(self) -> bool:
        return bool(self.username or self.password)

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    def server_url(self) -> str:
        """Endpoint without credentials -- what Chrome's --proxy-server wants."""
        return f"{self.protocol}://{self.address}"

    def url(self) -> str:
        """Full endpoint including credentials -- what requests/pip style clients want."""
        if self.has_auth:
            user = urllib.parse.quote(self.username, safe="")
            secret = urllib.parse.quote(self.password, safe="")
            return f"{self.protocol}://{user}:{secret}@{self.address}"
        return self.server_url()

    def describe(self) -> str:
        bits = [self.source.upper(), f"{self.protocol}://{self.address}"]
        if self.label:
            bits.append(self.label)
        if self.carrier:
            bits.append(self.carrier)
        if self.location:
            bits.append(self.location)
        bits.append("auth" if self.has_auth else "whitelist")
        return "  |  ".join(bits)


def _parse_endpoint(raw: str, protocol: str) -> Proxy:
    parts = raw.strip().split(":", 3)
    if len(parts) < 2 or not parts[0] or not parts[1].isdigit():
        raise ProxyApiError(STATUS_OK, f"unparsable proxy endpoint {raw!r}", fatal=True)
    return Proxy(
        host=parts[0],
        port=int(parts[1]),
        username=parts[2] if len(parts) > 2 else "",
        password=parts[3] if len(parts) > 3 else "",
        protocol=protocol,
    )


def fetch(
    key: str,
    *,
    nhamang: str = "random",
    tinhthanh: str = "0",
    whitelist: str = "",
    protocol: str = "http",
    timeout: int = 30,
) -> Proxy:
    """Ask the API to rotate and return one fresh proxy. Raises ProxyApiError."""
    query = urllib.parse.urlencode(
        {
            "key": key,
            "nhamang": nhamang,
            "tinhthanh": str(tinhthanh),
            "whitelist": whitelist,
        }
    )
    request = urllib.request.Request(
        f"{API_URL}?{query}",
        headers={"User-Agent": "selenium-creation/1.0", "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as exc:
        raise ProxyApiError(exc.code, f"HTTP {exc.code} from the proxy API") from exc
    except urllib.error.URLError as exc:
        raise ProxyApiError(0, f"cannot reach the proxy API: {exc.reason}") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ProxyApiError(0, f"non-JSON response: {body[:200]!r}") from exc

    try:
        status = int(payload.get("status", 0))
    except (TypeError, ValueError):
        status = 0
    message = str(payload.get("message", "")).strip()

    if status != STATUS_OK:
        lowered = message.lower()
        fatal = any(hint in lowered for hint in _FATAL_HINTS)
        raise ProxyApiError(status, message or "unknown API error", fatal=fatal)

    field = "proxysocks5" if protocol.startswith("socks") else "proxyhttp"
    raw = str(payload.get(field) or "").strip()
    if not raw:
        raise ProxyApiError(status, f"response carried no {field!r} endpoint", fatal=True)

    proxy = _parse_endpoint(raw, protocol)
    # dataclass is frozen, so fold the metadata in via replace-on-construct.
    return Proxy(
        host=proxy.host,
        port=proxy.port,
        username=proxy.username,
        password=proxy.password,
        protocol=protocol,
        source="rotating",
        carrier=str(payload.get("Nha Mang", "") or ""),
        location=str(payload.get("Vi Tri", "") or ""),
        lifetime=message,
    )


def fetch_with_retry(
    key: str,
    *,
    max_retries: int = 5,
    retry_delay: int = 10,
    max_wait: int = 120,
    log=print,
    **kwargs,
) -> Proxy:
    """fetch() plus cooldown handling -- the API rate-limits rotation per key."""
    last: ProxyApiError | None = None

    for attempt in range(1, max_retries + 1):
        try:
            return fetch(key, **kwargs)
        except ProxyApiError as exc:
            last = exc
            if exc.fatal:
                raise
            if attempt == max_retries:
                break
            wait = min(exc.retry_after or retry_delay, max_wait)
            log(f"  [{attempt}/{max_retries}] {exc.message} -- retrying in {wait}s")
            time.sleep(wait)

    assert last is not None
    raise last
