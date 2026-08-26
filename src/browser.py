"""Launches a brand-new undetected Chrome bound to one rotating proxy."""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from proxy_client import Proxy
import proxy_ext

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


def _seleniumbase_proxy(proxy: Proxy | None) -> str | None:
    """SeleniumBase proxy string: user:pass@host:port, or scheme://host:port."""
    if proxy is None:
        return None
    if proxy.protocol.startswith("socks"):
        if proxy.has_auth:
            raise LaunchError(
                "Chrome cannot authenticate SOCKS5 proxies. Your key returned "
                "credentials, so set \"protocol\": \"http\" in config.json."
            )
        return f"socks5://{proxy.address}"
    if proxy.has_auth:
        return f"{proxy.username}:{proxy.password}@{proxy.address}"
    return proxy.address


def _launch_seleniumbase(proxy, profile_dir, headless, window_size):
    try:
        from seleniumbase import Driver
    except ImportError as exc:  # pragma: no cover
        raise LaunchError(
            "seleniumbase is not installed. Run setup.bat again."
        ) from exc

    return Driver(
        uc=True,
        proxy=_seleniumbase_proxy(proxy),
        user_data_dir=str(profile_dir),
        headless2=bool(headless),
        window_size=window_size,
        no_sandbox=True,
    )


def _launch_undetected(proxy, profile_dir, headless, window_size):
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

    if proxy is not None:
        if proxy.protocol.startswith("socks") and proxy.has_auth:
            raise LaunchError(
                "Chrome cannot authenticate SOCKS5 proxies. Your key returned "
                "credentials, so set \"protocol\": \"http\" in config.json."
            )
        options.add_argument(f"--proxy-server={proxy.server_url()}")
        if proxy.has_auth:
            extension = proxy_ext.build(proxy.username, proxy.password, parent=profile_dir.parent)
            options.add_argument(f"--load-extension={extension}")

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

    if engine in ("seleniumbase", "sb", "uc"):
        driver = _launch_seleniumbase(proxy, profile_dir, headless, window_size)
    elif engine in ("undetected", "undetected-chromedriver", "ucd"):
        driver = _launch_undetected(proxy, profile_dir, headless, window_size)
    else:
        raise LaunchError(
            f"unknown engine {engine!r} -- use 'seleniumbase' or 'undetected'"
        )

    return driver, profile_dir


def open_url(driver, url: str) -> None:
    """Navigate, preferring SeleniumBase's stealth reconnect when available."""
    reconnect = getattr(driver, "uc_open_with_reconnect", None)
    if callable(reconnect):
        reconnect(url, 4)
    else:
        driver.get(url)
