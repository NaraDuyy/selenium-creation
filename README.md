# selenium-creation

Double-click `run.bat` and you get a **brand-new [CloakBrowser](https://github.com/CloakHQ/CloakBrowser)**
behind a proxy. Every run builds a profile that has never existed before and
rolls a **new random fingerprint** — no cookies, no history, no identity carried
over from the last session.

**Static proxies win by default.** If `proxystatic.txt` has entries, one is used.
Otherwise it falls back to rotating a fresh IP from
[proxyxoay.shop](https://proxyxoay.shop). `bench.bat` measures both so the choice
is evidence, not a guess — see [Static vs rotating](#static-vs-rotating-measured).

## Quick start

```bat
setup.bat     :: once per machine
run.bat       :: every time you want a new browser
bench.bat     :: measure static vs rotating on your own connection
```

`setup.bat` finds Python, builds a `.venv`, installs the dependencies, and asks
for your rotating-proxy key if `proxykey.txt` isn't there yet.

## Static proxies

Put them in `proxystatic.txt`, one per line. These are used **before** the
rotating API, because they are faster and far more reliable (measured below).

```
171.236.167.44:27076:username:password | viettel-1
160.250.166.14:10056                   | whitelist-only
socks5://1.2.3.4:30056
```

`ip:port`, `ip:port:user:pass`, `user:pass@ip:port` and `scheme://user:pass@ip:port`
all parse. Text after `|` is a label for logs and the benchmark table. `#` starts
a comment. The file is **gitignored**.

With several listed, `static_select` decides which one:

| Value | Behaviour |
|---|---|
| `first` | top of the file (default) |
| `random` | pick one at random |
| `roundrobin` | next one each run, remembered in `.static_state.json` |
| `fastest` | whichever won the last `bench.bat`, read from `bench_results.json` |

Force either source with `run.bat --static` (fail rather than fall back) or
`run.bat --rotate` (ignore the static list).

## Your key

The key you got when you bought the plan lives on the first line of
`proxykey.txt`, on its own:

```
xIqD................Tlgg
```

`proxykey.txt` is **gitignored** — the key never leaves your machine. Lines
starting with `#` are ignored, so you can keep a note next to it.

## CloakBrowser key (optional)

Without a key you get the free Chromium 146 build. A free key from
[cloakbrowser.dev/free](https://cloakbrowser.dev/free) (GitHub sign-in) unlocks
the newest build, Chromium 151, limited to one open browser at a time.

Paste it into `.env` in the project folder:

```
CLOAKBROWSER_LICENSE_KEY=cb_xxxxxxxx
```

`run.bat` loads it and prints `CloakBrowser key loaded from .env`. The next
launch downloads the 151 build once (~500 MB). `.env` is **gitignored**, so the
key never leaves the PC; `.env.example` is the template that is committed.

A `CLOAKBROWSER_LICENSE_KEY` already set in Windows takes priority over `.env`.
Either one beats a key saved by `cloakbrowser login`
(`%USERPROFILE%\.cloakbrowser\license.key`), which is only used when neither is set.

## Saved profiles

Without `--profile`, every run is a brand-new computer that is thrown away on
close. A saved profile is the opposite: the **same computer every time** --
same fingerprint, same cookies and logins, same history.

```bat
run.bat --profile shop1              :: create on first use, reopen after
run.bat --profiles                   :: list saved profiles
run.bat --delete-profile shop1       :: delete one (asks first; --yes skips)
run.bat --profile shop1 --portable   :: new profile whose logins survive a move to another PC
```

Each profile is one folder under `saved/` (gitignored):

```
saved/shop1/
  profile.json   the identity: seed, CPU threads, memory, screen, timezone,
                 language, storage size, cache size, home country, usage log
  browser/       CloakBrowser's own data: cookies, logins, history, bookmarks,
                 site storage, saved passwords, cache (capped at 100 MB)
  downloads/     files downloaded in this profile
  .lock          only while the profile is open
```

**What stays fixed.** The first launch rolls an identity and writes it to
`profile.json`. Every later launch reuses it: the seed recreates the GPU,
canvas, audio and fonts; threads, screen, window, language, storage size and
**timezone** are read back. `--fingerprint` and `--language` are ignored for an
existing profile, and say so.

**Proxies.** A profile does not store a proxy -- proxies are bought daily, so
yesterday's would be dead. Instead it remembers its **home**: the country, ISP
(by network number, e.g. `AS7552` Viettel, `AS45899` VNPT) and province of the
first proxy it was opened through. On every later launch each proxy in
`proxystatic.txt` is looked up in parallel, and:

- proxies that carry no traffic are skipped;
- proxies in **another country are refused** -- if none is left in the home
  country, `run.bat` does not open the browser at all (exit code 7) and says
  which countries it did find. `--allow-other-country` overrides this;
- of the rest, the closest to home wins: same ISP and province, then same ISP,
  then same province. If even the best one is on a **different ISP or
  province**, `run.bat` shows a `WARNING` and asks `Open anyway? [y/N]` --
  Enter or anything but `y` cancels without opening a browser (exit code 8).
  `--yes` accepts without asking; with no console to answer, it counts as no.

A new IP from the same ISP in the same province each day looks like an
ordinary home connection being reassigned. The timezone stays where it was (a
real PC's clock does not move); in one-timezone countries like Vietnam that
never matters. `--no-proxy` with a profile is refused too when this PC's own
connection is outside the home country.

**Memory** is always this PC's real value, so opening a profile on a PC with a
different amount of RAM prints a note. **Portable cookies** can only be chosen
when the profile is created: Windows encrypts saved logins for one user account,
so without `--portable` a copied profile opens signed out.

**One profile, one window.** While a profile is open, a second `run.bat` on it is
refused -- two browsers writing one folder corrupt it. A lock left by a crash
is cleared automatically.

## Flags

Anything you pass to `run.bat` goes straight to the script:

| Flag | What it does |
|---|---|
| `--check` | Print the exit IP the browser really has, then quit. Best way to confirm rotation. |
| `--url <URL>` | Open this page instead of `start_url` from the config |
| `--no-proxy` | Skip every proxy and launch on your direct connection (for debugging) |
| `--static` | Force a static proxy; fail loudly rather than quietly rotating |
| `--rotate` | Force a rotating proxy even when static ones are listed |
| `--static-select <s>` | `first` / `random` / `roundrobin` / `fastest` for this run |
| `--headless` | No window. Implies no waiting — the script does its job and exits. |
| `--socks5` | Use the `proxysocks5` endpoint instead of `proxyhttp` |
| `--nhamang <c>` | Carrier for this run, e.g. `fpt`, `viettel`, `vnpt`, `random` |
| `--tinhthanh <n>` | Province code for this run, `0` = random |
| `--language <l>` | Browser language for this run, e.g. `en-US`, `vi-VN`, or `auto` to follow the proxy |
| `--fingerprint <n>` | Reuse a fingerprint seed printed by an earlier run instead of rolling a new one |
| `--skip-proxy-check` | Open the browser even when the proxy check says the proxy carries no traffic |
| `--profile <name>` | Open a saved profile, creating it on first use |
| `--profiles` | List saved profiles |
| `--delete-profile <name>` | Delete a saved profile (asks first) |
| `--yes` | Answer yes to every question: deleting, or a proxy on a different ISP/province |
| `--allow-other-country` | Open a profile through a proxy outside its home country |
| `--portable` | With a new profile: keep its logins working if copied to another PC |
| `--keep-profile` | Don't delete the throwaway browser profile on exit |

```bat
run.bat --check
run.bat --url https://whoer.net --nhamang viettel
run.bat --tinhthanh 0 --keep-profile
```

## config.json

Defaults for every run. Flags win over the file.

| Key | Default | Meaning |
|---|---|---|
| `fingerprint` | `random` | `random` rolls a new identity every launch; a number pins one |
| `match_proxy_geo` | `true` | Set timezone, language and WebRTC IP from the proxy's exit IP |
| `check_proxy` | `true` | Stop before opening a browser if the proxy carries no traffic |
| `google_search` | `true` | Make Google the address bar's search engine at launch |
| `language` | `en-US` | Browser language: menus, `navigator.languages`, `Accept-Language`. `auto` follows the proxy's country |
| `storage_quota_mb` | `10240` | Storage space reported to sites, in MB; `0` keeps CloakBrowser's ~0.5 GB, which reads as incognito |
| `prefer_static` | `true` | Use `proxystatic.txt` before the rotating API |
| `static_select` | `first` | Which static proxy to take when several are listed |
| `protocol` | `http` | `http` or `socks5` — which endpoint to take from the API |
| `nhamang` | `random` | Carrier filter |
| `tinhthanh` | `"0"` | Province code, `0` = random |
| `whitelist` | `""` | Extra IPv4 allowed to use the proxy |
| `start_url` | `https://whoer.net` | Page opened on launch |
| `headless` | `false` | Run without a window |
| `window_size` | `1280,860` | `width,height` |
| `api_timeout` | `30` | Seconds to wait on the API |
| `api_max_retries` | `5` | Attempts before giving up |
| `api_retry_delay` | `10` | Fallback wait when the API doesn't name one |
| `api_max_wait` | `120` | Cap on any single cooldown wait |
| `keep_profile` | `false` | Keep the throwaway profile directory |

The carrier and province code lists come from the vendor's docs page — the API
accepts whatever they publish there.

## Static vs rotating (measured)

Run `bench.bat` yourself — these are the numbers from this machine on 2026-08-26,
one static proxy against three rotations, three passes each.

| | acquire | cold | warm | throughput | success |
|---|---|---|---|---|---|
| direct (no proxy) | — | 377 ms | 63 ms | 56.1 Mbps | 100% |
| **static** | **0 s** | **456 ms** | **99 ms** | **38.3 Mbps** | **100%** |
| rotating #1 | 0.2 s | 1175 ms | 105 ms | 6.3 Mbps | 33% |
| rotating #2 | 59.2 s | — | — | — | **0% (dead)** |
| rotating #3 | 59.3 s | — | — | — | **0% (dead)** |

**Yes — static is faster, and by more than the throughput column alone suggests.**

Three separate reasons, in order of how much they actually cost you:

1. **Reliability.** Two of three rotations were completely dead, and the one that
   worked answered only a third of its requests. The static proxy answered 100%
   of them across every pass. A proxy that does not respond is infinitely slow,
   and this is by far the biggest effect.

2. **The rotation cooldown.** The API rate-limits rotation per key — this key
   sits at roughly **60 seconds**. That is a full minute of waiting before Chrome
   even starts, on every launch that rotates. Static is a file read: zero.

3. **One hop instead of two.** Rotating proxies all came back on the *same*
   gateway, `160.250.166.14:10056`, which then forwards to whichever residential
   line is currently assigned. The static proxy's exit IP is its own address —
   you connect straight to the line. That extra shared hop is where the 6x
   throughput gap and the 2.6x cold-start gap come from.

### Read the throughput column carefully

Residential bandwidth is a lottery. Measuring the **same** endpoint six times in
a row gave 4.5–14.5 Mbps — a 3.2x swing from nothing but luck. So a single
benchmark run showing "static 3x faster" proves very little on its own.

That is why `--repeat` exists, and why the tool prints a `CAUTION` line when one
endpoint's own spread is wide enough to explain the verdict. The static result
above is trustworthy because it was stable across passes (37.8–41.7 Mbps, a 1.1x
spread) while the rotating ones were not.

```bat
bench.bat --repeat 3 --rotations 5
```

### So when is rotating still worth it?

When you *need* a different IP — one identity per account, per scrape, per
signup. That is what you are buying, and it costs you a minute of cooldown and a
real chance of a dead exit. For anything where the IP just has to not be yours,
static is the better tool.

## How it works

1. **`src/proxy_client.py`** calls `https://proxyxoay.shop/api/get.php` with your
   key. `status: 100` means success; anything else is an error in `message`.
   The endpoint arrives as `ip:port:user:pass` — the credential halves are empty
   when your key is bound to an IP whitelist instead.

   Rotation is rate-limited per key. When the API answers *"Con 3s moi co the doi
   proxy"* the client reads the number out of the message and waits exactly that
   long instead of guessing.

2. **`src/browser.py`** makes a profile directory under `profiles/` stamped with
   the time and a random suffix, so no two runs ever share state, rolls a
   fingerprint seed, and launches CloakBrowser on the proxy. The directory is
   deleted on exit unless you asked to keep it.

3. **`src/static_proxy.py`** reads `proxystatic.txt` and picks one entry.

### The browser

[CloakBrowser](https://github.com/CloakHQ/CloakBrowser) is a Chromium build with
fingerprint patches in its C++ source (canvas, WebGL, audio, GPU, WebRTC,
automation flags), driven through Playwright. `setup.bat` downloads the binary
(~535 MB on Windows, signature-verified) into `%USERPROFILE%\.cloakbrowser`.

**Random every launch.** With `"fingerprint": "random"` a new seed is rolled
each run and printed. The seed drives CloakBrowser's canvas, audio and GPU
patches, and also picks CPU threads and screen size from common real-world
values. Memory is not invented: CloakBrowser's `Sec-CH-Device-Memory` header
always reports the real PC, so `navigator.deviceMemory` is set to the same
value (Chrome's rounding of the installed RAM, capped at 32) and the threads
are drawn from what real machines with that much memory have. The screen always has room for the window plus taskbar and toolbar, so
with the default `window_size` of `1280,860` only 1680x1050, 1920x1080 and
2560x1440 are drawn — a smaller window unlocks more screen sizes.
`run.bat --fingerprint 48213` brings back the same machine.

**Consistent with the proxy.** Before launch, one request through the proxy asks
where its exit IP is. Timezone, `navigator.languages`/`Accept-Language` and the
WebRTC IP are then set to match — a Vietnamese exit IP gets `Asia/Bangkok` and
`vi-VN, vi, en-US, en` when `language` is `auto` (the default is `en-US`). If that lookup fails the browser still launches, on your
system timezone and language, and says so.

**Proxy credentials just work.** HTTP usernames and passwords go through
Playwright's proxy auth, and CloakBrowser authenticates SOCKS5 natively — so the
old loopback relay is gone and `--socks5` now works with credentials too.

**Address-bar search.** CloakBrowser ships with its search engine set to
"No Search", so typing a word like `hello` opens `http://hello/` and the proxy
answers `HTTP ERROR 503`. With `google_search` on, each launch adds Google on
the browser's own search settings page and makes it the default (~2 s, not
visible to websites). If a future CloakBrowser changes that page, the launch
carries on with a note instead of failing.

**Free tier limits.** Without a key you get Chromium 146 and **one browser at a
time**. Run `.venv\Scripts\python.exe -m cloakbrowser login` for the latest
binary (still one session); more concurrent sessions need a paid plan. The
binary is closed-source and checks its license with cloakbrowser.dev.

## Notes

- **Whitelist keys are tied to your IP.** If your key uses whitelist auth (no
  user/pass) and your home IP changes, add the new one via `whitelist` in
  `config.json` or the vendor dashboard, or the proxy will refuse you.
- **One browser at a time on the free tier.** Close the current window before
  starting another `run.bat`.
- **`--check` is the honest test.** These are residential gateways: the exit IP
  you get is usually *not* the gateway IP the API handed you. Comparing against
  your own IP is the only way to be sure the proxy is live.

## Requirements

- Windows, Python 3.9+ (Google Chrome is no longer needed — CloakBrowser ships its own)
- A proxyxoay.shop key with rotation enabled
