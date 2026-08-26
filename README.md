# selenium-creation

Double-click `run.bat` and you get a **brand-new undetected Chrome** behind a
proxy. Every run builds a Chrome profile that has never existed before — no
cookies, no history, no fingerprint carried over from the last session.

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
| `--engine <e>` | `seleniumbase` (default) or `undetected` |
| `--keep-profile` | Don't delete the throwaway Chrome profile on exit |

```bat
run.bat --check
run.bat --url https://whoer.net --nhamang viettel
run.bat --tinhthanh 0 --keep-profile
```

## config.json

Defaults for every run. Flags win over the file.

| Key | Default | Meaning |
|---|---|---|
| `engine` | `seleniumbase` | Which undetected-Chrome engine to drive |
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
   the time and a random suffix, so no two runs ever share state, and points
   Chrome at the proxy. The directory is deleted on exit unless you asked to keep it.

3. **`src/static_proxy.py`** reads `proxystatic.txt` and picks one entry.

4. **`src/proxy_relay.py`** only matters for proxies that need a username and
   password. Chrome cannot take credentials on `--proxy-server` — it raises a
   native auth dialog WebDriver cannot reach.

   The usual workaround is an extension answering `onAuthRequired`, and that is
   what this repo shipped first. **It does not work on Chrome 137+**, which
   ignores `--load-extension` entirely: the extension never loads, no error is
   raised, and every page just comes back blank. That was verified here on
   Chrome 151 — the extension was confirmed absent from `chrome://extensions-internals`.

   So instead of asking Chrome to authenticate, this authenticates *for* it: a
   tiny relay on `127.0.0.1` injects `Proxy-Authorization` into each connection
   and pipes the rest upstream. Chrome talks to loopback and never sees a
   credential, which works on any Chrome version, headless or not.

### Engines

`seleniumbase` (default) is SeleniumBase's UC mode. It is actively maintained and
matches its driver to whatever Chrome you have — it was verified here against
Chrome 151.

`undetected` is the original `undetected-chromedriver`. Its last release is from
2023 and it does not patch cleanly against current Chrome, so it's kept only as a
fallback. It isn't installed by default:

```bat
.venv\Scripts\python.exe -m pip install undetected-chromedriver
```

## Notes

- **Whitelist keys are tied to your IP.** If your key uses whitelist auth (no
  user/pass) and your home IP changes, add the new one via `whitelist` in
  `config.json` or the vendor dashboard, or the proxy will refuse you.
- **SOCKS5 + credentials doesn't work.** Chrome cannot authenticate SOCKS
  proxies at all, and the relay only speaks HTTP. If your proxy needs
  credentials, stay on `http`. The script stops with that message rather than
  silently connecting direct.
- **`--check` is the honest test.** These are residential gateways: the exit IP
  you get is usually *not* the gateway IP the API handed you. Comparing against
  your own IP is the only way to be sure the proxy is live.

## Requirements

- Windows, Python 3.9+, Google Chrome
- A proxyxoay.shop key with rotation enabled
