"""Open one brand-new CloakBrowser behind a freshly rotated proxy.

Every run: pick a proxy, spin up CloakBrowser on a profile directory that has
never existed before with a freshly rolled fingerprint, and hand the window over.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import browser
import profiles
import proxy_client
import static_proxy

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
KEY_PATH = ROOT / "proxykey.txt"
ENV_PATH = ROOT / ".env"

DEFAULTS = {
    "fingerprint": "random",
    "match_proxy_geo": True,
    "check_proxy": True,
    "google_search": True,
    "storage_quota_mb": 10240,
    "language": "en-US",
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


def load_env() -> list[str]:
    """Copy KEY=value lines from .env into the environment. Returns names set.

    A variable already set in Windows wins, and empty values are skipped, so an
    untouched .env changes nothing. CloakBrowser reads its license key from
    CLOAKBROWSER_LICENSE_KEY, so a key pasted here is picked up automatically.
    """
    if not ENV_PATH.exists():
        return []
    loaded = []
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if value and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded


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
        description="Launch a fresh CloakBrowser on a newly rotated proxy.",
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
    parser.add_argument("--language",
                        help='browser language, e.g. en-US or vi-VN; "auto" follows the proxy')
    parser.add_argument("--fingerprint",
                        help='"random" (default) or a seed number to reuse an identity')
    parser.add_argument("--skip-proxy-check", action="store_true",
                        help="open the browser even if the proxy carries no traffic")
    parser.add_argument("--keep-profile", action="store_true",
                        help="do not delete the throwaway browser profile on exit")
    parser.add_argument("--profile", metavar="NAME",
                        help="open a saved profile (created on first use) -- same computer every time")
    parser.add_argument("--profiles", action="store_true", help="list saved profiles and exit")
    parser.add_argument("--delete-profile", metavar="NAME", help="delete a saved profile and exit")
    parser.add_argument("--portable", action="store_true",
                        help="new profile only: keep its logins working if copied to another PC")
    parser.add_argument("--yes", action="store_true", help="do not ask before deleting")
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


def report_exit_ip(session) -> None:
    """Prove the browser is really behind the proxy, not the local connection."""
    print(f"      checking exit IP via {IP_ECHO}")
    try:
        session.page.goto(IP_ECHO, wait_until="domcontentloaded")
        body = session.page.inner_text("body").strip()
        print(f"      exit IP  {body}")
    except Exception as exc:
        print(f"      could not read the exit IP: {type(exc).__name__}: {exc}")


def wait_until_closed(session) -> None:
    """Block while the user drives the browser; return once it is gone."""
    print("\nBrowser is yours. Close the window (or press Ctrl+C) to finish.")
    try:
        # Playwright only notices closed tabs while it is called into, so wait
        # on whichever tab is still open rather than sleeping.
        while session.context.pages:
            session.context.pages[0].wait_for_timeout(1000)
        print("\nBrowser window closed.")
    except KeyboardInterrupt:
        print("\nCtrl+C -- shutting down.")
    except Exception:
        print("\nBrowser window closed.")


def show_profiles() -> int:
    saved = profiles.list_profiles()
    if not saved:
        print("No saved profiles yet. Create one with:  run.bat --profile NAME")
        return 0
    print(f"{'NAME':16} {'LAST USED':19} {'RUNS':>4} {'SIZE':>8}  IDENTITY")
    for p in saved:
        size = profiles.folder_size(p.path) / 1e6
        locked = "  (open now)" if p.lock_path.exists() else ""
        print(f"{p.name:16} {p.data.get('last_used', '-'):19} {p.data.get('launches', 0):>4} "
              f"{size:>6.1f}MB  {p.summary()}{locked}")
    print(f"\n{len(saved)} profile(s) in {profiles.SAVED_ROOT}")
    return 0


def remove_profile(name: str, assume_yes: bool) -> int:
    try:
        profile = profiles.open_profile(name)
        if not profile.path.exists():
            print(f"No saved profile named {name!r}. See:  run.bat --profiles")
            return 6
        size = profiles.folder_size(profile.path) / 1e6
        if not assume_yes:
            answer = input(f"Delete profile {name!r} ({size:.1f} MB) with its cookies and "
                           "history? This cannot be undone. [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                print("Kept.")
                return 0
        profiles.delete_profile(name)
        print(f"Deleted profile {name!r} ({size:.1f} MB freed).")
        return 0
    except profiles.ProfileError as exc:
        print(exc)
        return 6


def main(argv=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    env_loaded = load_env()
    config = load_config()

    if args.profiles:
        return show_profiles()
    if args.delete_profile:
        return remove_profile(args.delete_profile, args.yes)

    if args.language:
        config["language"] = args.language
    if args.fingerprint:
        config["fingerprint"] = args.fingerprint
    if args.skip_proxy_check:
        config["check_proxy"] = False
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
    print("  selenium-creation  |  fresh CloakBrowser + rotated proxy")
    print("=" * 62)
    if "CLOAKBROWSER_LICENSE_KEY" in env_loaded:
        print("      CloakBrowser key loaded from .env")

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

    launch_kwargs = dict(
        headless=config["headless"],
        window_size=config["window_size"],
        fingerprint=config["fingerprint"],
        match_geo=config["match_proxy_geo"],
        check_proxy=config["check_proxy"],
        google_search=config["google_search"],
        storage_quota_mb=config["storage_quota_mb"],
        language=config["language"],
    )
    profile = None
    if args.profile:
        try:
            profile = profiles.open_profile(args.profile)
            profiles.lock(profile)
        except profiles.ProfileError as exc:
            print(f"\n{exc}")
            return 6
        launch_kwargs.update(profile_dir=profile.browser_dir, downloads_dir=profile.downloads_dir,
                             cache_mb=profile.data.get("cache_mb", profiles.CACHE_MB))
        if profile.is_new:
            launch_kwargs["portable_cookies"] = args.portable
        else:
            saved = profile.data
            ignored = [flag for flag, given in (("--fingerprint", args.fingerprint),
                                                ("--language", args.language),
                                                ("--portable", args.portable)) if given]
            if ignored:
                print(f"      note        {', '.join(ignored)} ignored: profile {profile.name!r} "
                      "keeps the settings it was created with")
            launch_kwargs.update(
                fingerprint=saved["seed"],
                window_size=saved.get("window_size", config["window_size"]),
                language=saved.get("language") or config["language"],
                storage_quota_mb=saved.get("storage_quota_mb", config["storage_quota_mb"]),
                portable_cookies=saved.get("portable_cookies", False),
                pinned=profiles.pinned_settings(profile),
            )

    print("[2/3] Launching CloakBrowser ...")
    session = None
    profile_dir = None
    try:
        session, profile_dir = browser.launch(proxy, **launch_kwargs)
        identity = session.identity
        if profile is None:
            print(f"      profile     {profile_dir.name}")
            print(f"      fingerprint {session.seed}  (reuse with --fingerprint {session.seed})")
        else:
            if profile.is_new:
                timezone = identity.timezone or session.page.evaluate(
                    "Intl.DateTimeFormat().resolvedOptions().timeZone")
                profiles.record_first_launch(
                    profile, identity, timezone=timezone,
                    window_size=launch_kwargs["window_size"],
                    storage_quota_mb=launch_kwargs["storage_quota_mb"],
                    cache_mb=launch_kwargs["cache_mb"], portable=args.portable)
                print(f"      profile     {profile.name}  (NEW -- identity saved)")
            else:
                print(f"      profile     {profile.name}  (launch #{profile.data.get('launches', 0) + 1}, "
                      f"created {profile.data.get('created', '?')[:10]})")
                if profile.data.get("memory_gb") not in (None, identity.memory_gb):
                    print(f"      note        this PC reports {identity.memory_gb} GB of memory; the profile "
                          f"was created on one reporting {profile.data['memory_gb']} GB")
                home = profile.data.get("home_country")
                if home and identity.country and identity.country != home:
                    print(f"      WARNING     proxy is in {identity.country}, but this profile's home is "
                          f"{home}. Sites may ask you to verify -- a same-country proxy is safer.")
            profiles.record_launch(profile, identity)
            profile.save()
            print(f"      fingerprint {session.seed}  (saved in the profile)")
        print(f"      identity    {identity.describe()}")
        for note in identity.notes:
            print(f"      note        {note}")
        if args.check:
            print("[3/3] Verifying the connection")
            report_exit_ip(session)
        else:
            print(f"[3/3] Opening {start_url}")
            try:
                browser.open_url(session, start_url)
            except browser.NavigationError as exc:
                print(f"      {exc}")
                if config["headless"]:
                    return 4
                print("      The browser is still open -- try the page again or go elsewhere.")
            # Headless has no window for anyone to close, so do not block on it.
            if not config["headless"]:
                wait_until_closed(session)
    except browser.ProxyUnreachable as exc:
        print(f"\nThe proxy is not working, so no browser was opened:\n      {exc}")
        print("      Check it is still active and that this PC's IP is allowed to use it,")
        print("      pick another proxy, or run with --skip-proxy-check to open anyway.")
        return 5
    except browser.LaunchError as exc:
        print(f"\nCould not start CloakBrowser:\n{exc}")
        return 3
    finally:
        if session is not None:
            browser.shutdown(session)
        if profile is not None:
            profiles.unlock(profile)
        elif profile_dir is not None and not config["keep_profile"]:
            browser.discard_profile(profile_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
