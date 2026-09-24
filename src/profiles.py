"""Saved profiles: one folder per identity, reopened as the same computer.

    saved/<name>/profile.json   the identity -- seed, hardware, timezone, language
    saved/<name>/browser/       CloakBrowser's own data: cookies, history, cache
    saved/<name>/downloads/     files downloaded while the profile was open
    saved/<name>/.lock          present while a run.bat has the profile open

The seed recreates the GPU, canvas and audio fingerprint; profile.json pins
everything else, so the same name comes back as the same machine every time.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

SAVED_ROOT = Path(__file__).resolve().parent.parent / "saved"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
CACHE_MB = 100


class ProfileError(RuntimeError):
    pass


class ProfileLocked(ProfileError):
    """Another run.bat already has this profile open."""


class CountryMismatch(ProfileError):
    """No usable proxy is in the profile's home country."""


class NotConfirmed(ProfileError):
    """The best proxy differs from home and the user did not say yes."""


def home_of(data: dict) -> dict:
    return {"country": data.get("home_country"), "asn": data.get("home_asn"),
            "isp": data.get("home_isp"), "region": data.get("home_region")}


def match(data: dict, info) -> tuple[int, list[str]]:
    """Score how much a proxy looks like this profile's usual connection.

    Same ISP counts double: changing provider is rarer than a new address in a
    neighbouring province. Returns (score, human-readable differences).
    """
    home = home_of(data)
    score, diffs = 0, []
    if home["asn"] or home["isp"]:
        if (home["asn"] and info.asn == home["asn"]) or (not home["asn"] and info.isp == home["isp"]):
            score += 2
        else:
            diffs.append(f"different ISP: {info.network()} (usually {home['isp']} {home['asn'] or ''})".rstrip())
    if home["region"]:
        if info.region == home["region"]:
            score += 1
        else:
            diffs.append(f"different province: {info.region or '?'} (usually {home['region']})")
    return score, diffs


@dataclass
class Profile:
    name: str
    path: Path
    data: dict = field(default_factory=dict)

    @property
    def browser_dir(self) -> Path:
        return self.path / "browser"

    @property
    def downloads_dir(self) -> Path:
        return self.path / "downloads"

    @property
    def meta_path(self) -> Path:
        return self.path / "profile.json"

    @property
    def lock_path(self) -> Path:
        return self.path / ".lock"

    @property
    def is_new(self) -> bool:
        return "seed" not in self.data

    def save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.meta_path)

    def summary(self) -> str:
        d = self.data
        if self.is_new:
            return "not launched yet"
        screen = "x".join(str(v) for v in d.get("screen", []))
        home = " / ".join(x for x in (d.get("home_country"), d.get("home_isp"), d.get("home_region")) if x)
        return (f"seed {d['seed']}, {d.get('cores')} cores, {d.get('memory_gb')} GB, {screen}, "
                f"{d.get('language')}, {d.get('timezone')}, home {home or '-'}")


def _check_name(name: str) -> str:
    if not NAME_PATTERN.match(name or ""):
        raise ProfileError(
            f"profile names use letters, digits, dot, dash or underscore (max 40): {name!r}"
        )
    return name


def open_profile(name: str) -> Profile:
    """Load a saved profile, or start a new one if the name is unused."""
    path = SAVED_ROOT / _check_name(name)
    data = {}
    meta = path / "profile.json"
    if meta.exists():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProfileError(f"{meta} is damaged ({exc}); fix or delete it") from exc
    return Profile(name=name, path=path, data=data)


def list_profiles() -> list[Profile]:
    if not SAVED_ROOT.exists():
        return []
    return [open_profile(p.name) for p in sorted(SAVED_ROOT.iterdir())
            if p.is_dir() and NAME_PATTERN.match(p.name)]


def folder_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _pid_alive(pid: int) -> bool:
    """Whether a process still runs. os.kill(pid, 0) would send Ctrl+C on Windows."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def lock(profile: Profile) -> None:
    """Claim the profile for this process; two browsers on one folder corrupt it."""
    profile.path.mkdir(parents=True, exist_ok=True)
    if profile.lock_path.exists():
        try:
            owner = int(profile.lock_path.read_text().split()[0])
        except (ValueError, IndexError, OSError):
            owner = -1
        if owner != os.getpid() and _pid_alive(owner):
            raise ProfileLocked(
                f"profile {profile.name!r} is already open (process {owner}). "
                "Close that browser first."
            )
    profile.lock_path.write_text(f"{os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')}\n")


def unlock(profile: Profile) -> None:
    try:
        if profile.lock_path.exists() and profile.lock_path.read_text().split()[0] == str(os.getpid()):
            profile.lock_path.unlink()
    except (OSError, IndexError):
        pass


def delete_profile(name: str) -> int:
    """Remove a profile folder. Returns the bytes freed."""
    profile = open_profile(name)
    if not profile.path.exists():
        raise ProfileError(f"no saved profile named {name!r}")
    lock(profile)  # refuses while open elsewhere
    size = folder_size(profile.path)
    shutil.rmtree(profile.path)
    return size


def pinned_settings(profile: Profile) -> dict:
    """What browser.launch must hold fixed to recreate this profile's machine."""
    d = profile.data
    return {"cores": d.get("cores"), "screen": d.get("screen"), "timezone": d.get("timezone")}


def record_first_launch(profile: Profile, identity, *, timezone: str, window_size: str,
                        storage_quota_mb: int, cache_mb: int, portable: bool) -> None:
    profile.data.update({
        "name": profile.name,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed": identity.seed,
        "cores": identity.cores,
        "memory_gb": identity.memory_gb,
        "screen": list(identity.screen),
        "window_size": window_size,
        "timezone": timezone,
        "language": identity.locale,
        "storage_quota_mb": storage_quota_mb,
        "cache_mb": cache_mb,
        "portable_cookies": portable,
        "home_country": identity.country,
        "launches": 0,
    })


def record_launch(profile: Profile, identity) -> None:
    profile.data["launches"] = int(profile.data.get("launches", 0)) + 1
    profile.data["last_used"] = time.strftime("%Y-%m-%d %H:%M:%S")
    profile.data["last_exit_ip"] = identity.exit_ip
    profile.data["last_country"] = identity.country
    if not profile.data.get("home_country") and identity.country:
        profile.data["home_country"] = identity.country
    if identity.country and identity.country == profile.data.get("home_country"):
        # Fill in home ISP and province once, from the first proxy in the home country.
        for key, value in (("home_isp", identity.isp), ("home_asn", identity.asn),
                           ("home_region", identity.region)):
            if value and not profile.data.get(key):
                profile.data[key] = value
    profile.data["last_isp"] = identity.isp
    profile.data["last_region"] = identity.region
