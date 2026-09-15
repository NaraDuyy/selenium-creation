"""Launches a brand-new CloakBrowser bound to one proxy, with a random identity."""

from __future__ import annotations

import random
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from proxy_client import Proxy

PROFILE_ROOT = Path(__file__).resolve().parent.parent / "profiles"

# CloakBrowser's own seed range, so a pinned seed looks like a random one.
SEED_MIN, SEED_MAX = 10000, 99999

# Common real-world values. Repeats weight the draw toward what most PCs report.
SCREENS = [(1920, 1080), (1920, 1080), (1920, 1080), (1536, 864), (1600, 900),
           (1680, 1050), (1440, 900), (2560, 1440), (1366, 768)]
CORES = [4, 6, 8, 8, 8, 12, 12, 16]
MEMORY_GB = [4, 8, 8, 8]  # Chrome caps navigator.deviceMemory at 8
SCREEN_CHROME_MARGIN = 140  # Windows taskbar (~48px) + tabs and address bar (~85px)

# Primary language a browser in that country usually reports.
COUNTRY_LOCALE = {
    "VN": "vi-VN", "TH": "th-TH", "ID": "id-ID", "MY": "ms-MY", "PH": "en-PH",
    "SG": "en-SG", "JP": "ja-JP", "KR": "ko-KR", "CN": "zh-CN", "TW": "zh-TW",
    "HK": "zh-HK", "IN": "en-IN", "US": "en-US", "CA": "en-CA", "GB": "en-GB",
    "AU": "en-AU", "DE": "de-DE", "FR": "fr-FR", "ES": "es-ES", "IT": "it-IT",
    "NL": "nl-NL", "PL": "pl-PL", "RU": "ru-RU", "BR": "pt-BR", "MX": "es-MX",
}

GEO_LOOKUPS = (
    # (url, ip key, country key, timezone key)
    ("http://ip-api.com/json/?fields=status,query,countryCode,timezone",
     "query", "countryCode", "timezone"),
    ("https://ipinfo.io/json", "ip", "country", "timezone"),
)


class LaunchError(RuntimeError):
    pass


@dataclass
class Identity:
    """Everything the page can see about who this browser is."""

    seed: int
    cores: int
    memory_gb: int
    screen: tuple[int, int]
    exit_ip: str | None = None
    country: str | None = None
    timezone: str | None = None
    locale: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def accept_languages(self) -> str | None:
        if not self.locale:
            return None
        base = self.locale.split("-")[0]
        if base == "en":
            return f"{self.locale},en"
        return f"{self.locale},{base},en-US,en"

    def args(self) -> list[str]:
        width, height = self.screen
        args = [
            f"--fingerprint={self.seed}",
            f"--fingerprint-hardware-concurrency={self.cores}",
            f"--fingerprint-device-memory={self.memory_gb}",
            f"--fingerprint-screen-width={width}",
            f"--fingerprint-screen-height={height}",
        ]
        if self.timezone:
            args.append(f"--fingerprint-timezone={self.timezone}")
        if self.locale:
            args += [f"--lang={self.locale}", f"--accept-lang={self.accept_languages}"]
        if self.exit_ip:
            # WebRTC reports the proxy's exit IP rather than nothing or our own.
            args.append(f"--fingerprint-webrtc-ip={self.exit_ip}")
        return args

    def describe(self) -> str:
        width, height = self.screen
        bits = [f"{self.cores} cores", f"{self.memory_gb} GB", f"{width}x{height}"]
        bits.append(self.locale or "system language")
        bits.append(self.timezone or "system timezone")
        if self.exit_ip:
            bits.append(f"exit {self.exit_ip} ({self.country})")
        return ", ".join(bits)


@dataclass
class Session:
    """One running browser: the persistent context, its first tab, and its identity."""

    context: Any
    page: Any
    identity: Identity

    @property
    def seed(self) -> int:
        return self.identity.seed


def new_profile_dir() -> Path:
    """A never-before-used profile path, so every run is a virgin browser."""
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return PROFILE_ROOT / f"{stamp}-{uuid.uuid4().hex[:8]}"


def discard_profile(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def pick_seed(fingerprint) -> int:
    """``"random"`` rolls a new identity; an integer pins one you liked."""
    if fingerprint is None or str(fingerprint).strip().lower() in ("", "random"):
        return random.randint(SEED_MIN, SEED_MAX)
    try:
        return int(fingerprint)
    except (TypeError, ValueError):
        raise LaunchError(
            f'fingerprint must be "random" or a whole number, not {fingerprint!r}'
        ) from None


def roll_hardware(seed: int, window: tuple[int, int]) -> tuple[int, int, tuple[int, int]]:
    """Cores, memory and screen drawn from the seed, so one seed is one machine.

    The screen must hold the window plus the taskbar and browser toolbar;
    otherwise Chromium clamps outerHeight below innerHeight, a contradiction no
    real browser shows (seen on 1600x900 with an 860px-tall window).
    """
    rng = random.Random(seed)
    screens = [s for s in SCREENS
               if s[0] >= window[0] and s[1] >= window[1] + SCREEN_CHROME_MARGIN] or [(2560, 1440)]
    return rng.choice(CORES), rng.choice(MEMORY_GB), rng.choice(screens)


def _proxy_url(proxy: Proxy) -> str:
    scheme = "socks5" if proxy.protocol.startswith("socks") else "http"
    if not proxy.has_auth:
        return f"{scheme}://{proxy.address}"
    user, password = quote(proxy.username, safe=""), quote(proxy.password, safe="")
    return f"{scheme}://{user}:{password}@{proxy.address}"


def lookup_geo(proxy: Proxy, timeout: float = 10) -> tuple[str, str, str]:
    """Ask, through the proxy, where its exit IP is. Returns (ip, country, timezone)."""
    import httpx  # installed with cloakbrowser

    errors = []
    for url, ip_key, country_key, tz_key in GEO_LOOKUPS:
        try:
            data = httpx.get(url, proxy=_proxy_url(proxy), timeout=timeout).json()
            if data.get(ip_key) and data.get(tz_key):
                return data[ip_key], data.get(country_key) or "", data[tz_key]
            errors.append(f"{url}: incomplete answer")
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}")
    raise LaunchError("could not locate the proxy exit IP (" + "; ".join(errors) + ")")


def build_identity(seed: int, proxy: Proxy | None, window: tuple[int, int],
                   match_geo: bool) -> Identity:
    cores, memory_gb, screen = roll_hardware(seed, window)
    identity = Identity(seed=seed, cores=cores, memory_gb=memory_gb, screen=screen)
    if proxy is None or not match_geo:
        return identity
    try:
        identity.exit_ip, identity.country, identity.timezone = lookup_geo(proxy)
    except LaunchError as exc:
        # Launching anyway is still useful; the page just sees this PC's timezone.
        identity.notes.append(f"{exc} -- timezone/language left at system defaults")
        return identity
    identity.locale = COUNTRY_LOCALE.get(identity.country.upper(), "en-US")
    return identity


def _proxy_settings(proxy: Proxy | None) -> dict | None:
    """Hand the proxy to CloakBrowser with its credentials in separate fields.

    No local relay is needed any more: HTTP credentials go through Playwright's
    proxy auth, and CloakBrowser's patched Chromium authenticates SOCKS5 itself.
    """
    if proxy is None:
        return None
    scheme = "socks5" if proxy.protocol.startswith("socks") else "http"
    settings = {"server": f"{scheme}://{proxy.address}"}
    if proxy.has_auth:
        settings["username"] = proxy.username
        settings["password"] = proxy.password
    return settings


def _parse_window_size(window_size: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in str(window_size).split(","))
    except ValueError:
        raise LaunchError(
            f'window_size must look like "1280,860", not {window_size!r}'
        ) from None
    return width, height


def launch(proxy: Proxy | None, *, profile_dir=None, headless=False,
           window_size="1280,860", fingerprint="random", match_geo=True):
    """Return a live Session on a fresh profile, routed through ``proxy``."""
    try:
        from cloakbrowser import CloakBrowserLicenseError, launch_persistent_context
    except ImportError as exc:  # pragma: no cover
        raise LaunchError("cloakbrowser is not installed. Run setup.bat again.") from exc

    profile_dir = Path(profile_dir) if profile_dir else new_profile_dir()
    width, height = _parse_window_size(window_size)
    identity = build_identity(pick_seed(fingerprint), proxy, (width, height), match_geo)

    # Headed: no viewport emulation, so the page tracks the real window and
    # outerWidth >= innerWidth stays coherent. Headless has no window to track.
    viewport = {"width": width, "height": height} if headless else None

    try:
        context = launch_persistent_context(
            str(profile_dir),
            headless=bool(headless),
            proxy=_proxy_settings(proxy),
            # Our seed overrides CloakBrowser's own per-launch one so we can print it.
            args=identity.args() + [f"--window-size={width},{height}"],
            viewport=viewport,
        )
    except CloakBrowserLicenseError as exc:
        raise LaunchError(f"CloakBrowser refused the license: {exc}") from exc

    page = context.pages[0] if context.pages else context.new_page()
    return Session(context=context, page=page, identity=identity), profile_dir


def shutdown(session: Session) -> None:
    """Close the browser and the Playwright instance behind it."""
    try:
        session.context.close()
    except Exception:
        pass


def open_url(session: Session, url: str) -> None:
    session.page.goto(url, wait_until="domcontentloaded")
