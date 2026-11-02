"""End-to-end soak test: start the API, stream fake data at it, check the results.

Checks:
  1. the server stays up for the whole run
  2. every bad packet is rejected and counted (in total and per node)
  3. dropped counts match the seq numbers the generator skipped
  4. stored data loads back and matches what was sent, row for row
  5. per-node packet rate in /stats matches the configured rate

Deliverable run (4 nodes, 10 minutes, over UDP like real devices):
    python soak_test.py --nodes 4 --duration 600
Quick check:
    python soak_test.py --duration 20
Over MQTT (broker must be running, see DOCUMENTATION.md):
    python soak_test.py --transport mqtt --duration 60
"""

import argparse
import os
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

import fake_sender
from app.storage import load_session

HERE = Path(__file__).resolve().parent
WARMUP_S = 7  # ignore rate samples until the 5 s rate window is full


def free_port(kind: int) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def fingerprint(pkt: dict) -> int:
    return hash((pkt["seq"], pkt["ts_device_us"], pkt["rssi"], pkt["channel"],
                 pkt["bandwidth_mhz"], pkt["csi_len"], tuple(pkt["csi"])))


def rss_mb(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return int(out) / 1024 if out else 0.0


class Results:
    def __init__(self):
        self.failures = []

    def check(self, ok: bool, msg: str) -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {msg}")
        if not ok:
            self.failures.append(msg)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nodes", type=int, default=4, choices=range(1, fake_sender.MAX_NODES + 1))
    ap.add_argument("--rate", type=float, default=100)
    ap.add_argument("--duration", type=float, default=600)
    ap.add_argument("--transport", choices=["udp", "mqtt", "http"], default="udp")
    ap.add_argument("--mqtt-host", default="127.0.0.1")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--skip-rate", type=float, default=0.01)
    ap.add_argument("--bad-rate", type=float, default=0.01)
    ap.add_argument("--rate-tolerance", type=float, default=0.10, help="allowed relative error in rate_hz")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--keep", action="store_true", help="keep the recorded data even if the test passes")
    args = ap.parse_args()

    data_dir = Path(tempfile.mkdtemp(prefix="wavehome-soak-"))
    http_port = free_port(socket.SOCK_STREAM)
    udp_port = free_port(socket.SOCK_DGRAM)
    env = {"WAVEHOME_DATA_DIR": str(data_dir), "WAVEHOME_UDP_PORT": str(udp_port)}
    mqtt_topic = f"wavehome-soak-{http_port}/csi"  # unique so other publishers on the broker don't interfere
    if args.transport == "mqtt":
        env |= {"WAVEHOME_MQTT_HOST": args.mqtt_host, "WAVEHOME_MQTT_PORT": str(args.mqtt_port),
                "WAVEHOME_MQTT_TOPIC": f"{mqtt_topic}/#"}

    log_path = data_dir / "server.log"
    print(f"data dir: {data_dir}")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(http_port), "--log-level", "warning"],
        cwd=HERE, env={**os.environ, **env},
        stdout=log_path.open("w"), stderr=subprocess.STDOUT,
    )
    api = httpx.Client(base_url=f"http://127.0.0.1:{http_port}", timeout=5)

    try:
        health = None
        for _ in range(100):
            try:
                health = api.get("/health").json()
                if args.transport != "mqtt" or health["mqtt"]["connected"]:
                    break
            except httpx.HTTPError:
                pass
            if server.poll() is not None:
                print(log_path.read_text())
                return 1
            time.sleep(0.2)
        else:
            print("server did not become ready (is the MQTT broker running?)")
            return 1
        session_dir = data_dir / health["session"]

        sent_fp: dict[str, dict[int, int]] = {}

        def on_valid(pkt):
            sent_fp.setdefault(pkt["node_id"], {})[pkt["seq"]] = fingerprint(pkt)

        samples = []  # (elapsed, {node: rate_hz})
        peak_rss = 0.0
        stop = threading.Event()
        t0 = time.monotonic()

        def poll():
            nonlocal peak_rss
            while not stop.wait(10):
                elapsed = time.monotonic() - t0
                if server.poll() is not None:
                    print(f"\n!! server exited at {elapsed:.0f}s")
                    return
                try:
                    s = api.get("/stats").json()
                except httpx.HTTPError as e:
                    print(f"\n!! /stats failed at {elapsed:.0f}s: {e}")
                    continue
                rss = rss_mb(server.pid)
                peak_rss = max(peak_rss, rss)
                samples.append((elapsed, {n: v["rate_hz"] for n, v in s["nodes"].items()}))
                rates = " ".join(f"{n}={v['rate_hz']:.0f}Hz" for n, v in sorted(s["nodes"].items()) if n != "unknown")
                print(f"\r[{elapsed:5.0f}s] {rates}  accepted={s['totals']['accepted']} "
                      f"rejected={s['totals']['rejected']} dropped={s['totals']['dropped']} "
                      f"server_rss={rss:.0f}MB      ", end="", flush=True)

        poller = threading.Thread(target=poll, daemon=True)
        poller.start()

        cfg = fake_sender.Config(
            nodes=args.nodes, rate=args.rate, duration=args.duration, signal="mixed", period=30,
            transport=args.transport, host="127.0.0.1" if args.transport == "udp" else args.mqtt_host,
            udp_port=udp_port, mqtt_port=args.mqtt_port, mqtt_topic=mqtt_topic,
            http_url=f"http://127.0.0.1:{http_port}",
            skip_rate=args.skip_rate, bad_rate=args.bad_rate, seed=args.seed, progress=False,
        )
        print(f"sending: {args.nodes} nodes x {args.rate:g} Hz for {args.duration:g}s over {args.transport}, "
              f"skip={args.skip_rate:g} bad={args.bad_rate:g}")
        counters = fake_sender.run(cfg, on_valid=on_valid)
        time.sleep(2)  # let the server drain its socket
        stop.set()
        poller.join()
        print()

        r = Results()
        alive = server.poll() is None
        r.check(alive, f"server stayed up for {args.duration:g}s (peak memory {peak_rss:.0f} MB)")
        if not alive:
            print(log_path.read_text())
            return 1

        stats = api.get("/stats").json()
        nodes = stats["nodes"]

        total_bad = sum(counters.bad.values())
        r.check(stats["totals"]["rejected"] == total_bad,
                f"rejected total: backend {stats['totals']['rejected']} vs generator {total_bad} {dict(counters.bad)}")
        for node, n in sorted(counters.bad_by_node.items()):
            got = nodes.get(node, {}).get("rejected", 0)
            r.check(got == n, f"{node}: rejected {got} vs expected {n}")

        for node, sent in sorted(counters.sent.items()):
            st = nodes.get(node, {})
            seqs = sorted(sent_fp[node])
            # The backend can only see gaps between the first and last packet it received.
            expected_drop = sum(1 for s in counters.skipped[node] if seqs[0] < s < seqs[-1])
            r.check(st.get("accepted") == sent, f"{node}: accepted {st.get('accepted')} vs sent {sent}")
            r.check(st.get("dropped") == expected_drop,
                    f"{node}: dropped {st.get('dropped')} vs skipped {expected_drop}")
            r.check(st.get("out_of_order") == 0, f"{node}: out_of_order {st.get('out_of_order')}")

        expected_rate = args.rate * (1 - args.skip_rate)
        for node in sorted(counters.sent):
            vals = [s[node] for t, s in samples if t > WARMUP_S and node in s]
            if not vals:
                r.check(False, f"{node}: no rate samples (run longer than {WARMUP_S + 10}s)")
                continue
            med = statistics.median(vals)
            r.check(abs(med - expected_rate) <= args.rate_tolerance * expected_rate,
                    f"{node}: rate_hz median {med:.1f} (min {min(vals):.1f}) vs expected {expected_rate:.1f}")

        # Stop the server cleanly so files are closed, then read everything back.
        server.send_signal(signal.SIGINT)
        server.wait(timeout=10)
        t = time.monotonic()
        loaded = load_session(session_dir)
        load_s = time.monotonic() - t
        r.check(set(loaded) == set(counters.sent), f"stored nodes {sorted(loaded)} ({load_s:.1f}s to load)")
        for node, rows in sorted(loaded.items()):
            expected = sent_fp.get(node, {})
            mismatched = sum(1 for p in rows if expected.get(p["seq"]) != fingerprint(p))
            in_order = all(a["seq"] < b["seq"] for a, b in zip(rows, rows[1:]))
            r.check(len(rows) == len(expected) and mismatched == 0 and in_order,
                    f"{node}: {len(rows)} rows loaded, {mismatched} differ from what was sent, "
                    f"{'in' if in_order else 'OUT OF'} order")

        print(f"\n{'PASSED' if not r.failures else f'FAILED ({len(r.failures)})'}")
        if r.failures or args.keep:
            print(f"data kept in {data_dir}")
        else:
            shutil.rmtree(data_dir)
        return 1 if r.failures else 0
    finally:
        if server.poll() is None:
            server.send_signal(signal.SIGINT)
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    sys.exit(main())
