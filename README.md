# selenium-creation

Double-click `run.bat` and you get a **brand-new undetected Chrome** behind a
**freshly rotated proxy** from [proxyxoay.shop](https://proxyxoay.shop). Every run
rotates a new exit IP and builds a Chrome profile that has never existed before —
no cookies, no history, no fingerprint carried over from the last session.

## Quick start

```bat
setup.bat     :: once per machine
run.bat       :: every time you want a new browser
```

`setup.bat` finds Python, builds a `.venv`, installs the dependencies, and asks
for your rotating-proxy key if `proxykey.txt` isn't there yet.

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
| `--no-proxy` | Skip the API and launch on your direct connection (for debugging) |
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

3. **`src/proxy_ext.py`** only matters for keys that return a username and
   password. Chrome can't take credentials on `--proxy-server`; it raises a native
   auth dialog WebDriver can't reach. So this writes a throwaway Manifest V3
   extension that answers `onAuthRequired`. Routing still comes from
   `--proxy-server`, so nothing leaks before the service worker wakes up.

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
  proxies at all. If your key returns credentials, stay on `http`. The script
  stops with that message rather than silently connecting direct.
- **`--check` is the honest test.** These are residential gateways: the exit IP
  you get is usually *not* the gateway IP the API handed you. Comparing against
  your own IP is the only way to be sure the proxy is live.

## Requirements

- Windows, Python 3.9+, Google Chrome
- A proxyxoay.shop key with rotation enabled
