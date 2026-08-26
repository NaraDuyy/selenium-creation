"""Launches a brand-new undetected Chrome bound to one proxy."""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from proxy_client import Proxy
from proxy_relay import ProxyRelay

PROFILE_ROOT = Path(__file__).resolve().parent.parent / "profiles"


class LaunchError(RuntimeError):
    pass


def new_profile_dir() -> Path:
    """A never-before-used profile path, so every run is a virgin browser."""
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return PROFILE_ROOT / f"{stamp}-{uuid.uuid4().hex[:8]}"


def discard_profile(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _prepare(proxy: Proxy | None) -> tuple[str | None, ProxyRelay | None]:
    """Work out what to hand Chrome, starting a credential relay if needed.

    Chrome has no way to accept a proxy username and password: it raises a native
    dialog WebDriver cannot click. Extensions used to paper over that, but Chrome
    137+ ignores --load-extension, so on a current Chrome the extension never
    loads and every page silently comes back blank.

    A loopback relay sidesteps the problem: it holds the credentials, Chrome just
    talks to 127.0.0.1 unauthenticated.
    """
    if proxy is None:
        return None, None

    if proxy.protocol.startswith("socks"):
        if proxy.has_auth:
            raise LaunchError(
                "Chrome cannot authenticate SOCKS5 proxies, and the relay only "
                'speaks HTTP. Set "protocol": "http" in config.json, or use a '
                "SOCKS endpoint without credentials."
            )
        return f"socks5://{proxy.address}", None

    if not proxy.has_auth:
        return proxy.address, None

    relay = ProxyRelay(proxy.host, proxy.port, proxy.username, proxy.password)
    relay.start()
    return relay.address, relay


def _launch_seleniumbase(proxy_arg, profile_dir, headless, window_size):
    try:
        from seleniumbase import Driver
    except ImportError as exc:  # pragma: no cover
        raise LaunchError("seleniumbase is not installed. Run setup.bat again.") from exc

    return Driver(
        uc=True,
        proxy=proxy_arg,
        user_data_dir=str(profile_dir),
        headless2=bool(headless),
        window_size=window_size,
        no_sandbox=True,
    )


def _launch_undetected(proxy_arg, profile_dir, headless, window_size):
    try:
        import undetected_chromedriver as uc
    except ImportError as exc:
        raise LaunchError(
            "undetected-chromedriver is not installed. Either install it with\n"
            r"  .venv\Scripts\python.exe -m pip install undetected-chromedriver" "\n"
            'or set "engine": "seleniumbase" in config.json (recommended).'
        ) from exc

    options = uc.ChromeOptions()
    options.add_argument(f"--window-size={window_size}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    if proxy_arg:
        server = proxy_arg if "://" in proxy_arg else f"http://{proxy_arg}"
        options.add_argument(f"--proxy-server={server}")

    return uc.Chrome(
        options=options,
        user_data_dir=str(profile_dir),
        headless=bool(headless),
        use_subprocess=False,
    )


def launch(proxy: Proxy | None, *, engine="seleniumbase", profile_dir=None,
           headless=False, window_size="1280,860"):
    """Return a live WebDriver on a fresh profile, routed through ``proxy``."""
    profile_dir = Path(profile_dir) if profile_dir else new_profile_dir()
    engine = (engine or "seleniumbase").lower()

    proxy_arg, relay = _prepare(proxy)
    try:
        if engine in ("seleniumbase", "sb", "uc"):
            driver = _launch_seleniumbase(proxy_arg, profile_dir, headless, window_size)
        elif engine in ("undetected", "undetected-chromedriver", "ucd"):
            driver = _launch_undetected(proxy_arg, profile_dir, headless, window_size)
        else:
            raise LaunchError(
                f"unknown engine {engine!r} -- use 'seleniumbase' or 'undetected'"
            )
    except BaseException:
        if relay is not None:
            relay.stop()
        raise

    # Carried on the driver so shutdown() can close it without extra plumbing.
    driver._proxy_relay = relay
    return driver, profile_dir


def shutdown(driver) -> None:
    """Quit the browser and tear down its credential relay, if any."""
    relay = getattr(driver, "_proxy_relay", None)
    try:
        driver.quit()
    except Exception:
        pass
    if relay is not None:
        relay.stop()


def open_url(driver, url: str) -> None:
    """Navigate, preferring SeleniumBase's stealth reconnect when available."""
    reconnect = getattr(driver, "uc_open_with_reconnect", None)
    if callable(reconnect):
        reconnect(url, 4)
    else:
        driver.get(url)
