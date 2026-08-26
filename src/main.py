"""Open one brand-new undetected Chrome behind a freshly rotated proxy.

Every run: hit the proxyxoay.shop API for a new exit IP, spin up Chrome on a
profile directory that has never existed before, and hand the window over.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import browser
import proxy_client
import static_proxy

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
KEY_PATH = ROOT / "proxykey.txt"

DEFAULTS = {
    "engine": "seleniumbase",
    "protocol": "http",
    "nhamang": "random",
    "tinhthanh": "0",
    "whitelist": "",
    "prefer_static": True,
    "static_select": "first",
    "start_url": "https://whoer.net",
    "headless": False,
    "window_size": "1280,860",
    "api_timeout": 30,
    "api_max_retries": 5,
    "api_retry_delay": 10,
    "api_max_wait": 120,
    "keep_profile": False,
}


def load_config() -> dict:
    config = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"config.json is not valid JSON: {exc}")
    return config


def load_key() -> str:
    if not KEY_PATH.exists():
        raise SystemExit(
            f"No key file at {KEY_PATH}.\nRun setup.bat, or paste your "
            "proxyxoay key into proxykey.txt."
        )
    # Tolerate comment lines so the file can carry a note next to the key.
    for line in KEY_PATH.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if candidate and not candidate.startswith("#"):
            if candidate.upper().startswith("PASTE-YOUR"):
                break
            return candidate
    raise SystemExit(
        f"{KEY_PATH} has no key in it. Paste the key you got when you bought "
        "the rotating-proxy plan."
    )


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="run.bat",
        description="Launch a fresh undetected Chrome on a newly rotated proxy.",
    )
    parser.add_argument("--url", help="page to open instead of config start_url")
    parser.add_argument("--no-proxy", action="store_true",
                        help="skip every proxy and launch on a direct connection")
    parser.add_argument("--static", action="store_true",
                        help="force a static proxy, fail rather than fall back")
    parser.add_argument("--rotate", action="store_true",
                        help="force a rotating proxy even when static ones exist")
    parser.add_argument("--static-select",
                        choices=["first", "random", "roundrobin", "fastest"],
                        help="which static proxy to take when several are listed")
    parser.add_argument("--headless", action="store_true", help="run without a window")
    parser.add_argument("--socks5", action="store_true",
                        help="use the socks5 endpoint instead of http")
    parser.add_argument("--nhamang", help="carrier override, e.g. fpt / viettel / vnpt")
    parser.add_argument("--tinhthanh", help="province code override, 0 = random")
    parser.add_argument("--engine", choices=["seleniumbase", "undetected"],
                        help="which undetected-Chrome engine to drive")
    parser.add_argument("--keep-profile", action="store_true",
                        help="do not delete the throwaway Chrome profile on exit")
    parser.add_argument("--check", action="store_true",
                        help="print the exit IP the browser is really using, then quit")
    return parser.parse_args(argv)


def obtain_static(config):
    """Return a static proxy if the list has one, else None."""
    try:
        proxies = static_proxy.load(config["protocol"])
    except static_proxy.StaticProxyError as exc:
        print(f"      static proxy list problem: {exc}")
        return None
    if not proxies:
        return None
    chosen = static_proxy.select(proxies, config["static_select"])
    print(f"      using {chosen.describe()}")
    print(f"      ({len(proxies)} static listed, picked by {config['static_select']!r})")
    return chosen


def obtain_rotating(config, key):
    print("      asking the API to rotate ...")
    proxy = proxy_client.fetch_with_retry(
        key,
        nhamang=config["nhamang"],
        tinhthanh=config["tinhthanh"],
        whitelist=config["whitelist"],
        protocol=config["protocol"],
        timeout=int(config["api_timeout"]),
        max_retries=int(config["api_max_retries"]),
        retry_delay=int(config["api_retry_delay"]),
        max_wait=int(config["api_max_wait"]),
    )
    print(f"      got  {proxy.describe()}")
    if proxy.lifetime:
        print(f"      note {proxy.lifetime}")
    return proxy


def choose_proxy(args, config):
    """Static wins unless told otherwise; rotating is the fallback."""
    want_static = config["prefer_static"] and not args.rotate
    if args.static:
        want_static = True

    if want_static:
        proxy = obtain_static(config)
        if proxy is not None:
            return proxy
        if args.static:
            raise SystemExit(
                "--static was requested but proxystatic.txt has no usable "
                "entries.\nPaste your static proxies in, one per line, "
                "then try again."
            )
        print("      no static proxies listed -- falling back to rotation")

    return obtain_rotating(config, load_key())


IP_ECHO = "https://api.ipify.org?format=json"


def report_exit_ip(driver) -> None:
    """Prove the browser is really behind the proxy, not the local connection."""
    print(f"      checking exit IP via {IP_ECHO}")
    try:
        driver.get(IP_ECHO)
        body = driver.find_element("tag name", "body").text.strip()
        print(f"      exit IP  {body}")
    except Exception as exc:
        print(f"      could not read the exit IP: {type(exc).__name__}: {exc}")


def wait_until_closed(driver) -> None:
    """Block while the user drives the browser; return once it is gone."""
    print("\nBrowser is yours. Close the window (or press Ctrl+C) to finish.")
    try:
        while True:
            time.sleep(1)
            _ = driver.window_handles  # raises once Chrome is gone
    except KeyboardInterrupt:
        print("\nCtrl+C -- shutting down.")
    except Exception:
        print("\nBrowser window closed.")


def main(argv=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    config = load_config()

    if args.engine:
        config["engine"] = args.engine
    if args.socks5:
        config["protocol"] = "socks5"
    if args.headless:
        config["headless"] = True
    if args.keep_profile:
        config["keep_profile"] = True
    if args.static_select:
        config["static_select"] = args.static_select
    if args.nhamang:
        config["nhamang"] = args.nhamang
    if args.tinhthanh:
        config["tinhthanh"] = args.tinhthanh
    start_url = args.url or config["start_url"]

    print("=" * 62)
    print("  selenium-creation  |  fresh undetected Chrome + rotated proxy")
    print("=" * 62)

    proxy = None
    if args.no_proxy:
        print("[1/3] Proxy skipped (--no-proxy): using a direct connection.")
    else:
        print("[1/3] Picking a proxy ...")
        try:
            proxy = choose_proxy(args, config)
        except proxy_client.ProxyApiError as exc:
            print(f"\nProxy API refused: {exc.message} (status {exc.status})")
            if exc.fatal:
                print("That looks permanent -- check the key in proxykey.txt.")
            return 2

    print(f"[2/3] Launching undetected Chrome via {config['engine']} ...")
    driver = None
    profile_dir = None
    try:
        driver, profile_dir = browser.launch(
            proxy,
            engine=config["engine"],
            headless=config["headless"],
            window_size=config["window_size"],
        )
        print(f"      profile {profile_dir.name}")
        if args.check:
            print("[3/3] Verifying the connection")
            report_exit_ip(driver)
        else:
            print(f"[3/3] Opening {start_url}")
            browser.open_url(driver, start_url)
            # Headless has no window for anyone to close, so do not block on it.
            if not config["headless"]:
                wait_until_closed(driver)
    except browser.LaunchError as exc:
        print(f"\nCould not start Chrome:\n{exc}")
        return 3
    finally:
        if driver is not None:
            browser.shutdown(driver)
        if profile_dir is not None and not config["keep_profile"]:
            browser.discard_profile(profile_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
