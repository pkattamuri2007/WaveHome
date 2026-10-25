"""Fake CSI generator so the team can build without hardware.

Simulates N receivers producing schema v0.1 packets and POSTs them to the
ingestion API (or prints JSON lines with --stdout).

Examples (from software/backend):
    python fake_sender.py                              # 2 nodes, 100 Hz, empty room, forever
    python fake_sender.py --scenario motion --duration 30
    python fake_sender.py --scenario mixed --drop-rate 0.02
    python fake_sender.py --stdout --duration 1 > sample.jsonl

Scenarios:
    empty   static channel plus small noise
    motion  per-subcarrier amplitude ripples, like a person walking through
    mixed   alternates empty / motion every --period seconds
"""

import argparse
import json
import math
import random
import sys
import time

import httpx

N_SUBCARRIERS = 64  # 20 MHz -> 64 subcarriers -> csi_len 128 (imag, real pairs)
NULL_SUBCARRIERS = {0, *range(27, 38)}  # DC and guard bands carry no data


class FakeNode:
    def __init__(self, node_id: str, rng: random.Random):
        self.node_id = node_id
        self.rng = rng
        self.seq = 0
        # Each node sees a different but fixed room response.
        self.base_amp = [
            0.0 if k in NULL_SUBCARRIERS else 30 + 15 * math.sin(k / 6 + rng.uniform(0, 6)) + rng.uniform(-3, 3)
            for k in range(N_SUBCARRIERS)
        ]
        self.phase_slope = rng.uniform(-0.3, 0.3)
        self.phase_offset = rng.uniform(-math.pi, math.pi)
        self.rssi_base = rng.randint(-60, -40)
        self.motion_freqs = [rng.uniform(0.5, 3.0) for _ in range(N_SUBCARRIERS)]

    def packet(self, t: float, moving: bool, channel: int) -> dict:
        csi = []
        for k in range(N_SUBCARRIERS):
            amp = self.base_amp[k]
            if amp and moving:
                amp *= 1 + 0.35 * math.sin(2 * math.pi * self.motion_freqs[k] * t + k / 4)
            amp += self.rng.gauss(0, 0.8 if amp else 0)
            phase = self.phase_offset + self.phase_slope * k + self.rng.gauss(0, 0.05)
            imag = max(-128, min(127, round(amp * math.sin(phase))))
            real = max(-128, min(127, round(amp * math.cos(phase))))
            csi += [imag, real]  # esp-csi order: imaginary then real (to be confirmed on hardware)

        rssi = self.rssi_base + round(self.rng.gauss(0, 3 if moving else 1))
        pkt = {
            "schema_version": "0.1",
            "node_id": self.node_id,
            "seq": self.seq,
            "ts_device_us": int(t * 1_000_000),
            "rssi": min(rssi, 0),
            "channel": channel,
            "bandwidth_mhz": 20,
            "csi_len": len(csi),
            "csi": csi,
        }
        self.seq += 1
        return pkt


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8000", help="ingestion API base URL")
    ap.add_argument("--nodes", type=int, default=2, help="number of fake receivers")
    ap.add_argument("--rate", type=float, default=100, help="packets per second per node")
    ap.add_argument("--duration", type=float, default=0, help="seconds to run (0 = forever)")
    ap.add_argument("--scenario", choices=["empty", "motion", "mixed"], default="empty")
    ap.add_argument("--period", type=float, default=10, help="seconds per phase in mixed scenario")
    ap.add_argument("--drop-rate", type=float, default=0.0, help="fraction of packets to silently drop")
    ap.add_argument("--channel", type=int, default=6)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--stdout", action="store_true", help="print JSON lines instead of POSTing")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    nodes = [FakeNode(f"rx{i + 1}", rng) for i in range(args.nodes)]
    tick = 0.1  # send in batches 10x per second to keep HTTP overhead low
    per_tick = args.rate * tick
    owed = 0.0
    start = time.monotonic()
    sent = dropped = ticks = 0
    client = None if args.stdout else httpx.Client(base_url=args.url, timeout=5)

    try:
        while not args.duration or time.monotonic() - start < args.duration:
            elapsed = time.monotonic() - start
            moving = args.scenario == "motion" or (
                args.scenario == "mixed" and int(elapsed // args.period) % 2 == 1
            )
            owed += per_tick
            n, owed = int(owed), owed - int(owed)
            batch = []
            for i in range(n):
                t = time.time() + i / args.rate
                for node in nodes:
                    pkt = node.packet(t, moving, args.channel)
                    if rng.random() < args.drop_rate:
                        dropped += 1  # seq still advanced, so the backend should see a gap
                        continue
                    batch.append(pkt)

            if args.stdout:
                for pkt in batch:
                    print(json.dumps(pkt))
            elif batch:
                r = client.post("/ingest/batch", json=batch)
                if r.status_code != 200:
                    print(f"server rejected batch: {r.status_code} {r.text[:300]}", file=sys.stderr)
            sent += len(batch)

            ticks += 1
            if not args.stdout and ticks % 10 == 0:
                print(f"\r{elapsed:6.1f}s  sent={sent}  dropped={dropped}  "
                      f"{'MOTION' if moving else 'empty '}", end="", file=sys.stderr)

            time.sleep(max(0.0, start + ticks * tick - time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        if client:
            client.close()
        print(f"\ndone: sent={sent} dropped={dropped}", file=sys.stderr)


if __name__ == "__main__":
    main()
