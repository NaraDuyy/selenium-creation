"""Loads the static proxy list from staticproxy.txt.

Static proxies are endpoints you already own, so there is no API and no rotation
cooldown -- the file *is* the source. One proxy per line, ``#`` starts a comment
line, and all of the usual shapes are understood::

    160.250.166.14:10056
    160.250.166.14:10056:user:pass
    user:pass@160.250.166.14:10056
    http://user:pass@160.250.166.14:10056
    socks5://160.250.166.14:30056
    160.250.166.14:10056:user:pass | hanoi-1

Anything after a ``|`` is a free-text label used in logs and benchmark tables.
"""

from __future__ import annotations

import json
import random
import urllib.parse
from pathlib import Path

from proxy_client import Proxy

ROOT = Path(__file__).resolve().parent.parent

# proxystatic.txt is the canonical name (it pairs with proxykey.txt); the other
# spelling is accepted too because it is the easy one to type by mistake.
LIST_NAMES = ("proxystatic.txt", "staticproxy.txt")
STATE_PATH = ROOT / ".static_state.json"
BENCH_PATH = ROOT / "bench_results.json"

_PLACEHOLDER = "PASTE-YOUR-STATIC"


class StaticProxyError(RuntimeError):
    pass


def _parse_line(line: str, default_protocol: str) -> Proxy:
    label = ""
    if "|" in line:
        line, _, label = line.partition("|")
        line, label = line.strip(), label.strip()

    protocol = default_protocol
    if "://" in line:
        scheme, _, line = line.partition("://")
        protocol = scheme.strip().lower() or default_protocol

    username = password = ""
    if "@" in line:
        creds, _, line = line.rpartition("@")
        username, _, password = creds.partition(":")
        username = urllib.parse.unquote(username)
        password = urllib.parse.unquote(password)

    parts = line.split(":", 3)
    if len(parts) < 2 or not parts[0] or not parts[1].strip().isdigit():
        raise StaticProxyError(f"cannot read a host:port out of {line!r}")

    host, port = parts[0].strip(), int(parts[1].strip())
    # ip:port:user:pass form -- only when credentials were not already given as user@
    if not username and len(parts) > 2:
        username = parts[2]
        password = parts[3] if len(parts) > 3 else ""

    return Proxy(
        host=host,
        port=port,
        username=username,
        password=password,
        protocol=protocol,
        source="static",
        label=label,
    )


def list_path() -> Path | None:
    """First static list that actually exists, or None."""
    for name in LIST_NAMES:
        candidate = ROOT / name
        if candidate.exists():
            return candidate
    return None


def load(protocol: str = "http", path: Path | None = None) -> list[Proxy]:
    """Every usable static proxy in the file. Empty list when there are none."""
    path = path or list_path()
    if path is None or not path.exists():
        return []

    proxies: list[Proxy] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.upper().startswith(_PLACEHOLDER):
            continue
        try:
            proxies.append(_parse_line(line, protocol))
        except StaticProxyError as exc:
            raise StaticProxyError(f"{path.name} line {number}: {exc}") from exc
    return proxies


def _next_round_robin(count: int) -> int:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        index = int(state.get("index", -1))
    except (OSError, ValueError, json.JSONDecodeError):
        index = -1
    index = (index + 1) % count
    try:
        STATE_PATH.write_text(json.dumps({"index": index}), encoding="utf-8")
    except OSError:
        pass
    return index


def _fastest(proxies: list[Proxy]) -> Proxy | None:
    """Pick whichever static proxy won the last benchmark, if we have one."""
    try:
        results = json.loads(BENCH_PATH.read_text(encoding="utf-8"))["results"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None

    ranked = {
        r["address"]: r["warm_ms_median"]
        for r in results
        if r.get("source") == "static" and r.get("ok") and r.get("warm_ms_median")
    }
    scored = [(ranked[p.address], p) for p in proxies if p.address in ranked]
    if not scored:
        return None
    return min(scored, key=lambda pair: pair[0])[1]


def select(proxies: list[Proxy], strategy: str = "first") -> Proxy:
    """Choose one proxy out of the list according to ``strategy``."""
    if not proxies:
        raise StaticProxyError("no static proxies to choose from")

    strategy = (strategy or "first").lower()
    if strategy == "random":
        return random.choice(proxies)
    if strategy in ("roundrobin", "round-robin", "rr"):
        return proxies[_next_round_robin(len(proxies))]
    if strategy == "fastest":
        return _fastest(proxies) or proxies[0]
    return proxies[0]
