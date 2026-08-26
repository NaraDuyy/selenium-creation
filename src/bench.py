"""Measures static proxies against rotating ones, with a direct-connection baseline.

Three numbers matter, and they are not the same number:

* **acquire**    -- how long it takes to *get* a working proxy. Static is a file
                    read. Rotating is an API round trip plus whatever cooldown
                    the vendor imposes, and that cost is real on every launch.
* **cold**       -- first request on a new connection: proxy CONNECT + TLS
                    handshake. This is what you pay on every fresh browser.
* **warm**       -- median request once the connection is up (keep-alive). This
                    is what page loads actually feel like.

Then throughput on a fixed-size download. Reported per proxy, plus a summary.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import proxy_client
import static_proxy
from proxy_client import Proxy

ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = ROOT / "bench_results.json"

LATENCY_URL = "https://speed.cloudflare.com/__down?bytes=0"
DOWNLOAD_URL = "https://speed.cloudflare.com/__down?bytes={bytes}"
IP_URL = "https://api.ipify.org"


@dataclass
class Result:
    label: str
    source: str
    address: str
    ok: bool = False
    acquire_ms: float | None = None
    cold_ms: float | None = None
    warm_ms_median: float | None = None
    warm_ms_min: float | None = None
    warm_ms_max: float | None = None
    throughput_mbps: float | None = None
    throughput_min: float | None = None
    throughput_max: float | None = None
    runs: int = 1
    success_rate: float = 0.0
    exit_ip: str | None = None
    error: str | None = None
    samples: list[float] = field(default_factory=list)


def _session(proxy: Proxy | None):
    import requests

    session = requests.Session()
    if proxy is not None:
        url = proxy.url()
        session.proxies = {"http": url, "https": url}
    session.headers["User-Agent"] = "selenium-creation-bench/1.0"
    session.trust_env = False  # ignore ambient HTTP_PROXY vars
    return session


def measure(
    proxy: Proxy | None,
    *,
    label: str,
    samples: int = 5,
    payload_bytes: int = 2_000_000,
    timeout: int = 30,
    acquire_ms: float | None = None,
) -> Result:
    source = proxy.source if proxy else "direct"
    address = proxy.address if proxy else "-"
    result = Result(label=label, source=source, address=address, acquire_ms=acquire_ms)

    session = _session(proxy)
    attempts = 0
    successes = 0

    try:
        # Cold: brand-new connection, so this includes CONNECT and the TLS handshake.
        start = time.perf_counter()
        response = session.get(LATENCY_URL, timeout=timeout)
        response.raise_for_status()
        result.cold_ms = round((time.perf_counter() - start) * 1000, 1)
        attempts += 1
        successes += 1
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {str(exc)[:120]}"
        result.success_rate = 0.0
        session.close()
        return result

    # Warm: same session, connection already established.
    warm: list[float] = []
    for _ in range(max(1, samples)):
        attempts += 1
        try:
            start = time.perf_counter()
            response = session.get(LATENCY_URL, timeout=timeout)
            response.raise_for_status()
            warm.append(round((time.perf_counter() - start) * 1000, 1))
            successes += 1
        except Exception:
            pass

    if warm:
        result.samples = warm
        result.warm_ms_median = round(statistics.median(warm), 1)
        result.warm_ms_min = min(warm)
        result.warm_ms_max = max(warm)

    # Throughput on a fixed payload.
    try:
        attempts += 1
        start = time.perf_counter()
        response = session.get(
            DOWNLOAD_URL.format(bytes=payload_bytes), timeout=timeout, stream=True
        )
        response.raise_for_status()
        received = sum(len(chunk) for chunk in response.iter_content(65536))
        elapsed = time.perf_counter() - start
        if elapsed > 0 and received > 0:
            result.throughput_mbps = round((received * 8) / elapsed / 1_000_000, 2)
        successes += 1
    except Exception as exc:
        if not result.error:
            result.error = f"download: {type(exc).__name__}: {str(exc)[:90]}"

    try:
        result.exit_ip = session.get(IP_URL, timeout=timeout).text.strip()
    except Exception:
        pass

    session.close()
    result.success_rate = round(successes / attempts, 3) if attempts else 0.0
    result.ok = bool(result.warm_ms_median)
    return result


def measure_repeated(proxy, *, repeat=1, **kwargs) -> Result:
    """Run measure() several times and keep the median.

    A single pass is not trustworthy on residential lines -- the same endpoint
    can swing 3x between back-to-back runs. Repeating and reporting the spread
    is the difference between a number and a guess.
    """
    runs = [measure(proxy, **kwargs) for _ in range(max(1, repeat))]
    good = [r for r in runs if r.ok]
    if not good:
        return runs[0]

    merged = good[0]
    merged.runs = len(runs)

    warm = [r.warm_ms_median for r in good if r.warm_ms_median is not None]
    if warm:
        merged.warm_ms_median = round(statistics.median(warm), 1)
        merged.warm_ms_min = min(r.warm_ms_min for r in good if r.warm_ms_min is not None)
        merged.warm_ms_max = max(r.warm_ms_max for r in good if r.warm_ms_max is not None)

    speeds = [r.throughput_mbps for r in good if r.throughput_mbps is not None]
    if speeds:
        merged.throughput_mbps = round(statistics.median(speeds), 2)
        merged.throughput_min = min(speeds)
        merged.throughput_max = max(speeds)

    colds = [r.cold_ms for r in good if r.cold_ms is not None]
    if colds:
        merged.cold_ms = round(statistics.median(colds), 1)

    merged.success_rate = round(statistics.mean(r.success_rate for r in runs), 3)
    return merged


def collect_rotating(config, key, rotations, log=print):
    """Rotate ``rotations`` times, timing how long each acquisition really takes."""
    acquired = []
    for index in range(1, rotations + 1):
        log(f"  rotating {index}/{rotations} ...")
        start = time.perf_counter()
        try:
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
                log=lambda message: log(f"  {message}"),
            )
        except proxy_client.ProxyApiError as exc:
            log(f"  rotation {index} failed: {exc.message}")
            continue
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        log(f"    {proxy.describe()}  (acquired in {elapsed / 1000:.1f}s)")
        acquired.append((proxy, elapsed))
    return acquired


def _cell(value, suffix="", width=9):
    return (f"{value}{suffix}" if value is not None else "--").rjust(width)


def render(results) -> None:
    print()
    print("=" * 96)
    print("  RESULTS   (lower ms is better, higher Mbps is better)")
    print("=" * 96)
    print(
        f"{'proxy':<28}{'acquire':>9}{'cold':>10}{'warm':>10}"
        f"{'spread':>13}{'speed':>11}{'ok':>7}"
    )
    print("-" * 96)

    for result in results:
        spread = (
            f"{result.warm_ms_min:.0f}-{result.warm_ms_max:.0f}"
            if result.warm_ms_min is not None
            else "--"
        )
        acquire = (
            f"{result.acquire_ms / 1000:.1f}s" if result.acquire_ms is not None else "--"
        )
        print(
            f"{result.label[:28]:<28}"
            f"{acquire:>9}"
            f"{_cell(result.cold_ms, 'ms', 10)}"
            f"{_cell(result.warm_ms_median, 'ms', 10)}"
            f"{spread:>13}"
            f"{_cell(result.throughput_mbps, 'Mb', 11)}"
            f"{result.success_rate * 100:>6.0f}%"
        )
        if result.error:
            print(f"{'':<28}  ! {result.error}")
    print("-" * 96)


def summarise(results) -> None:
    def group(source):
        return [r for r in results if r.source == source and r.ok]

    static, rotating = group("static"), group("rotating")
    if not (static and rotating):
        print("\nNeed at least one working static AND one rotating proxy to compare.")
        if not static:
            print("Add your static proxies to proxystatic.txt, then run bench.bat again.")
        return

    def mean(rows, attr):
        values = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
        return statistics.mean(values) if values else None

    print("\n" + "=" * 96)
    print("  STATIC vs ROTATING")
    print("=" * 96)

    rows = [
        ("acquire (s)", "acquire_ms", 0.001, True),
        ("cold latency (ms)", "cold_ms", 1, True),
        ("warm latency (ms)", "warm_ms_median", 1, True),
        ("throughput (Mbps)", "throughput_mbps", 1, False),
    ]
    print(f"{'metric':<24}{'static':>14}{'rotating':>14}{'verdict':>28}")
    print("-" * 96)
    for name, attr, scale, lower_is_better in rows:
        s, r = mean(static, attr), mean(rotating, attr)
        if s is None or r is None:
            print(f"{name:<24}{'--':>14}{'--':>14}{'':>28}")
            continue
        s, r = s * scale, r * scale
        if min(s, r) <= 0:
            verdict = "static is free" if lower_is_better else ""
        else:
            better = (r / s) if lower_is_better else (s / r)
            if better >= 1.05:
                verdict = f"static {better:.1f}x better"
            elif better <= 0.95:
                verdict = f"rotating {1 / better:.1f}x better"
            else:
                verdict = "about the same"
        print(f"{name:<24}{s:>14.1f}{r:>14.1f}{verdict:>28}")
    print("-" * 96)


def _variance_caution(rows) -> None:
    """Warn when one endpoint's own spread swamps the static-vs-rotating gap.

    Residential lines are a lottery. If a single proxy varies more than the two
    groups differ, the verdict above is noise and should not be acted on.
    """
    spreads = [
        r.throughput_max / r.throughput_min
        for r in rows
        if r.throughput_min and r.throughput_max and r.throughput_min > 0 and r.runs > 1
    ]
    if not spreads:
        print()
        print("Only one pass per proxy -- re-run with --repeat 3 before trusting")
        print("the throughput column. Residential lines swing several x on their own.")
        return

    worst = max(spreads)
    if worst >= 1.5:
        print()
        print(f"CAUTION: a single endpoint varied {worst:.1f}x across its own repeats.")
        print("Any throughput verdict smaller than that is line lottery, not static-vs-rotating.")


def main(argv=None) -> int:
    sys.path.insert(0, str(ROOT / "src"))
    import main as app  # reuse config + key loading

    parser = argparse.ArgumentParser(
        prog="bench.bat", description="Measure static vs rotating proxy performance."
    )
    parser.add_argument("--rotations", type=int, default=3,
                        help="how many rotating proxies to sample (default 3)")
    parser.add_argument("--samples", type=int, default=5,
                        help="warm latency samples per proxy (default 5)")
    parser.add_argument("--bytes", type=int, default=2_000_000,
                        help="download size for the throughput test (default 2 MB)")
    parser.add_argument("--repeat", type=int, default=1,
                        help="passes per proxy; medians are reported (default 1)")
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--rotating-only", action="store_true")
    parser.add_argument("--no-direct", action="store_true",
                        help="skip the unproxied baseline row")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    config = app.load_config()
    results = []

    print("=" * 96)
    print("  selenium-creation  |  proxy benchmark")
    print(f"  {args.samples} warm samples x {args.repeat} pass(es), "
          f"{args.bytes / 1_000_000:.0f} MB download, {args.rotations} rotations")
    print("=" * 96)

    if not args.no_direct:
        print("\n[direct] no proxy, baseline")
        results.append(measure_repeated(None, repeat=args.repeat,
                                        label="direct (no proxy)",
                                        samples=args.samples, payload_bytes=args.bytes))

    if not args.rotating_only:
        statics = static_proxy.load(config["protocol"])
        if not statics:
            print("\n[static] staticproxy.txt is empty -- nothing to measure")
        for index, proxy in enumerate(statics, 1):
            name = proxy.label or f"static #{index}"
            print(f"\n[static] {name}  {proxy.address}")
            results.append(measure_repeated(proxy, repeat=args.repeat, label=name,
                                            samples=args.samples,
                                            payload_bytes=args.bytes, acquire_ms=0.0))

    if not args.static_only:
        print(f"\n[rotating] sampling {args.rotations} rotations")
        try:
            key = app.load_key()
        except SystemExit as exc:
            print(f"  skipped: {exc}")
            key = None
        if key:
            for index, (proxy, acquire_ms) in enumerate(
                collect_rotating(config, key, args.rotations), 1
            ):
                tag = " ".join(x for x in (proxy.carrier, proxy.location) if x)
                results.append(
                    measure_repeated(proxy, repeat=args.repeat,
                                     label=f"rotating #{index} {tag}".strip(),
                                     samples=args.samples, payload_bytes=args.bytes,
                                     acquire_ms=acquire_ms)
                )

    render(results)
    summarise(results)
    _variance_caution([r for r in results if r.ok])

    RESULTS_PATH.write_text(
        json.dumps(
            {"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
             "results": [asdict(r) for r in results]},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved to {RESULTS_PATH.name} -- static_select 'fastest' reads this file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
