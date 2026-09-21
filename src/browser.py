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

GOOGLE_SEARCH = ("Google", "google.com", "https://www.google.com/search?q=%s")

# What a stock Chrome reports from navigator.storage.estimate() -- measured at
# exactly 10 GiB on a real Chrome 152. CloakBrowser's own default is ~0.5 GB,
# which BrowserScan and Pixelscan read as an incognito window.
STORAGE_QUOTA_MB = 10240

GEO_LOOKUPS = (
    # (url, ip key, country key, timezone key)
    ("http://ip-api.com/json/?fields=status,query,countryCode,timezone",
     "query", "countryCode", "timezone"),
    ("https://ipinfo.io/json", "ip", "country", "timezone"),
)


class LaunchError(RuntimeError):
    pass


class ProxyUnreachable(LaunchError):
    """The proxy would not carry a single request, so a browser would load nothing."""


class NavigationError(RuntimeError):
    """The browser is up, but the page would not load."""


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


def _describe_error(exc: Exception) -> str:
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def lookup_geo(proxy: Proxy, timeout: float = 10) -> tuple[str, str, str]:
    """Ask, through the proxy, where its exit IP is. Returns (ip, country, timezone).

    Raises ProxyUnreachable when no lookup got any HTTP answer at all -- the
    proxy itself is broken -- and plain LaunchError when answers came back but
    were unusable, which says nothing bad about the proxy.
    """
    import httpx  # installed with cloakbrowser

    errors = []
    answered = False
    for url, ip_key, country_key, tz_key in GEO_LOOKUPS:
        try:
            response = httpx.get(url, proxy=_proxy_url(proxy), timeout=timeout)
        except httpx.TransportError as exc:
            errors.append(f"{url}: {_describe_error(exc)}")
            continue
        if response.status_code == 407:
            # Over plain http the proxy's own refusal arrives as a normal
            # response, but no traffic got past it.
            errors.append(f"{url}: proxy rejected the login (HTTP 407)")
            continue
        answered = True
        try:
            data = response.json()
        except ValueError:
            data = {}
        if data.get(ip_key) and data.get(tz_key):
            return data[ip_key], data.get(country_key) or "", data[tz_key]
        errors.append(f"{url}: HTTP {response.status_code} without a location")

    detail = "; ".join(errors)
    if not answered:
        raise ProxyUnreachable(f"{proxy.describe()} carried no traffic ({detail})")
    raise LaunchError(f"could not locate the proxy exit IP ({detail})")


def build_identity(seed: int, proxy: Proxy | None, window: tuple[int, int],
                   match_geo: bool, check_proxy: bool = True) -> Identity:
    cores, memory_gb, screen = roll_hardware(seed, window)
    identity = Identity(seed=seed, cores=cores, memory_gb=memory_gb, screen=screen)
    if proxy is None or not (match_geo or check_proxy):
        return identity
    try:
        exit_ip, country, timezone = lookup_geo(proxy)
    except ProxyUnreachable as exc:
        if check_proxy:
            raise
        identity.notes.append(f"{exc} -- launching anyway because check_proxy is off")
        return identity
    except LaunchError as exc:
        # Launching anyway is still useful; the page just sees this PC's timezone.
        identity.notes.append(f"{exc} -- timezone/language left at system defaults")
        return identity
    if not match_geo:
        return identity
    identity.exit_ip, identity.country, identity.timezone = exit_ip, country, timezone
    identity.locale = COUNTRY_LOCALE.get(country.upper(), "en-US")
    return identity


def set_google_search(page, timeout_ms: int = 5000) -> None:
    """Make Google the search engine the address bar uses.

    CloakBrowser ships with "No Search", so a word typed in the address bar is
    opened as http://word/ and the proxy answers 503. Google is not in its list
    either, so it is added the way a user would, through the search settings
    page -- which no website can see. Raises if that page has changed shape.
    """
    name, keyword, url = GOOGLE_SEARCH
    page.goto("chrome://settings/searchEngines")
    page.locator("#addSearchEngine").click(timeout=timeout_ms)
    page.locator("cr-input#searchEngine input").fill(name, timeout=timeout_ms)
    page.locator("cr-input#keyword input").fill(keyword, timeout=timeout_ms)
    page.locator("cr-input#queryUrl input").fill(url, timeout=timeout_ms)
    page.locator("cr-button#actionButton").click(timeout=timeout_ms)
    # Find the row by its shortcut and use element ids, never button labels:
    # the settings page follows the browser language, which tracks the proxy.
    entry = page.locator("settings-search-engine-entry").filter(has_text=keyword)
    entry.locator("cr-icon-button:not(#editIconButton)").click(timeout=timeout_ms)
    entry.locator("button#makeDefault").click(timeout=timeout_ms)

    default = page.evaluate("""async () => {
        const cr = await import('chrome://resources/js/cr.js');
        const list = await cr.sendWithPromise('getSearchEnginesList');
        const engine = [...(list.defaults || []), ...(list.actives || []), ...(list.others || [])]
            .find(e => e.default);
        return engine ? engine.name : null;
    }""")
    if default != name:
        raise RuntimeError(f"default search engine is still {default!r}")


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
           window_size="1280,860", fingerprint="random", match_geo=True,
           check_proxy=True, google_search=True, storage_quota_mb=STORAGE_QUOTA_MB):
    """Return a live Session on a fresh profile, routed through ``proxy``.

    With ``check_proxy`` a proxy that carries no traffic raises ProxyUnreachable
    before any browser is started.
    """
    try:
        from cloakbrowser import CloakBrowserLicenseError, launch_persistent_context
    except ImportError as exc:  # pragma: no cover
        raise LaunchError("cloakbrowser is not installed. Run setup.bat again.") from exc

    profile_dir = Path(profile_dir) if profile_dir else new_profile_dir()
    width, height = _parse_window_size(window_size)
    identity = build_identity(pick_seed(fingerprint), proxy, (width, height),
                              match_geo, check_proxy)

    # Headed: no viewport emulation, so the page tracks the real window and
    # outerWidth >= innerWidth stays coherent. Headless has no window to track.
    viewport = {"width": width, "height": height} if headless else None
    extra_args = [f"--window-size={width},{height}"]
    if storage_quota_mb:
        extra_args.append(f"--fingerprint-storage-quota={int(storage_quota_mb)}")

    try:
        context = launch_persistent_context(
            str(profile_dir),
            headless=bool(headless),
            proxy=_proxy_settings(proxy),
            # Our seed overrides CloakBrowser's own per-launch one so we can print it.
            args=identity.args() + extra_args,
            viewport=viewport,
        )
    except CloakBrowserLicenseError as exc:
        raise LaunchError(f"CloakBrowser refused the license: {exc}") from exc

    page = context.pages[0] if context.pages else context.new_page()
    if google_search:
        from playwright.sync_api import Error as PlaywrightError

        try:
            set_google_search(page)
        except (PlaywrightError, RuntimeError) as exc:
            # A browser without address-bar search is still worth handing over.
            reason = str(exc).splitlines()[0]
            identity.notes.append(
                f"could not set Google as the search engine ({reason}) -- "
                "type full addresses in the address bar"
            )
        try:
            page.goto("about:blank")
        except PlaywrightError:
            pass
    return Session(context=context, page=page, identity=identity), profile_dir


def shutdown(session: Session) -> None:
    """Close the browser and the Playwright instance behind it."""
    try:
        session.context.close()
    except Exception:
        pass


def open_url(session: Session, url: str, attempts: int = 2) -> None:
    """Navigate, retrying once: residential proxies and sites drop the odd connection."""
    from playwright.sync_api import Error as PlaywrightError

    for attempt in range(1, attempts + 1):
        try:
            session.page.goto(url, wait_until="domcontentloaded")
            return
        except PlaywrightError as exc:
            reason = str(exc).splitlines()[0]
            if attempt == attempts:
                raise NavigationError(f"could not open {url}: {reason}") from exc
            print(f"      attempt {attempt} failed ({reason}), retrying ...")
