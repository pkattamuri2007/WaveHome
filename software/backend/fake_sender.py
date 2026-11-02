"""Fake CSI receivers so the team can build and test without hardware.

Simulates 1-4 ESP32 receivers producing schema v0.1 packets and sends them the
way real devices will: one JSON packet per UDP datagram (default) or per MQTT
message. HTTP and stdout are there for tools and debugging.

Examples (from software/backend, with the API running):
    python fake_sender.py                                    # 2 nodes, 100 Hz, empty room, UDP, forever
    python fake_sender.py --nodes 4 --signal moving --duration 60
    python fake_sender.py --signal mixed --bad-rate 0.02 --skip-rate 0.01
    python fake_sender.py --transport mqtt                   # needs a broker, see DOCUMENTATION.md
    python fake_sender.py --transport stdout --duration 1 > sample.jsonl

Signals:
    empty   static channel plus small noise
    moving  per-subcarrier amplitude ripples, like a person walking through
    mixed   alternates empty / moving every --period seconds

Fault injection:
    --skip-rate  fraction of seq numbers that are never sent (backend should count them as dropped)
    --bad-rate   fraction of extra invalid packets (backend should reject and count them)
"""

import argparse
import json
import math
import random
import socket
import sys
import time
from collections import Counter
from dataclasses import dataclass, field

N_SUBCARRIERS = 64  # 20 MHz -> 64 subcarriers -> csi_len 128 (imag, real pairs)
NULL_SUBCARRIERS = {0, *range(27, 38)}  # DC and guard bands carry no data
MAX_NODES = 4

REQUIRED_FIELDS = [
    "schema_version", "node_id", "seq", "ts_device_us",
    "rssi", "channel", "bandwidth_mhz", "csi_len", "csi",
]
BAD_KINDS = ["missing_field", "wrong_type", "out_of_range", "len_mismatch", "not_json"]
WRONG_TYPES = {
    "schema_version": 0.1, "node_id": 7, "seq": "12", "ts_device_us": 1.5, "rssi": "-45",
    "channel": 6.0, "bandwidth_mhz": "20", "csi_len": None, "csi": "1 2 3",
}
OUT_OF_RANGE = {"rssi": 10, "bandwidth_mhz": 80, "seq": -1, "channel": 0, "csi": 500}


@dataclass
class Config:
    nodes: int = 2
    rate: float = 100.0          # packets per second per node
    duration: float = 0.0        # seconds, 0 = forever
    signal: str = "empty"
    period: float = 10.0         # seconds per phase for the mixed signal
    transport: str = "udp"
    host: str = "127.0.0.1"
    udp_port: int = 5005
    mqtt_port: int = 1883
    mqtt_topic: str = "wavehome/csi"  # packets go to <topic>/<node_id>
    http_url: str = "http://127.0.0.1:8000"
    skip_rate: float = 0.0
    bad_rate: float = 0.0
    bad_kinds: list[str] = field(default_factory=lambda: list(BAD_KINDS))
    channel: int = 6
    seed: int | None = None
    progress: bool = True


@dataclass
class Counters:
    sent: Counter = field(default_factory=Counter)         # valid packets per node
    skipped: dict = field(default_factory=dict)            # node -> skipped seq numbers
    bad: Counter = field(default_factory=Counter)          # bad packets per kind
    bad_by_node: Counter = field(default_factory=Counter)  # node the backend should blame ("unknown" if none)


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


def make_bad(pkt: dict, kind: str, rng: random.Random) -> dict | bytes:
    """Return an invalid version of pkt. not_json returns raw bytes."""
    if kind == "not_json":
        return json.dumps(pkt).encode()[:40]  # truncated mid-packet
    bad = dict(pkt)
    if kind == "missing_field":
        del bad[rng.choice(REQUIRED_FIELDS)]
    elif kind == "wrong_type":
        name = rng.choice(list(WRONG_TYPES))
        bad[name] = WRONG_TYPES[name]
    elif kind == "out_of_range":
        name = rng.choice(list(OUT_OF_RANGE))
        if name == "csi":
            bad["csi"] = list(pkt["csi"])
            bad["csi"][rng.randrange(len(bad["csi"]))] = OUT_OF_RANGE["csi"]
        else:
            bad[name] = OUT_OF_RANGE[name]
    elif kind == "len_mismatch":
        bad["csi_len"] = pkt["csi_len"] + 1
    else:
        raise ValueError(f"unknown bad packet kind: {kind}")
    return bad


def blamed_node(bad: dict | bytes) -> str:
    """The node_id the backend can attribute a rejected packet to."""
    node_id = bad.get("node_id") if isinstance(bad, dict) else None
    return node_id if isinstance(node_id, str) and node_id else "unknown"


class UdpSink:
    def __init__(self, cfg: Config):
        self.addr = (cfg.host, cfg.udp_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, node_id: str, payload: bytes) -> None:
        self.sock.sendto(payload, self.addr)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.sock.close()


class MqttSink:
    def __init__(self, cfg: Config):
        import paho.mqtt.client as mqtt

        self.topic = cfg.mqtt_topic
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.connect(cfg.host, cfg.mqtt_port)
        self.client.loop_start()
        self.last = None

    def send(self, node_id: str, payload: bytes) -> None:
        self.last = self.client.publish(f"{self.topic}/{node_id}", payload, qos=0)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        if self.last:
            self.last.wait_for_publish(timeout=5)
        self.client.disconnect()
        self.client.loop_stop()


class HttpSink:
    """Posts each tick's packets as one batch. Non-JSON payloads go to /ingest on their own."""

    def __init__(self, cfg: Config):
        import httpx

        self.client = httpx.Client(base_url=cfg.http_url, timeout=5)
        self.batch = []

    def send(self, node_id: str, payload: bytes) -> None:
        try:
            self.batch.append(json.loads(payload))
        except ValueError:
            self.client.post("/ingest", content=payload)

    def flush(self) -> None:
        if self.batch:
            self.client.post("/ingest/batch", json=self.batch)
            self.batch = []

    def close(self) -> None:
        self.flush()
        self.client.close()


class StdoutSink:
    def send(self, node_id: str, payload: bytes) -> None:
        sys.stdout.write(payload.decode(errors="replace") + "\n")

    def flush(self) -> None:
        pass

    def close(self) -> None:
        sys.stdout.flush()


SINKS = {"udp": UdpSink, "mqtt": MqttSink, "http": HttpSink, "stdout": lambda cfg: StdoutSink()}


def run(cfg: Config, on_valid=None) -> Counters:
    """Generate and send packets until cfg.duration elapses (or Ctrl-C).

    on_valid(pkt) is called for every valid packet sent, e.g. to check stored data later.
    """
    if not 1 <= cfg.nodes <= MAX_NODES:
        raise ValueError(f"nodes must be 1 to {MAX_NODES}")
    rng = random.Random(cfg.seed)
    nodes = [FakeNode(f"rx{i + 1}", rng) for i in range(cfg.nodes)]
    counters = Counters(skipped={n.node_id: [] for n in nodes})
    sink = SINKS[cfg.transport](cfg)

    tick = 0.02  # devices send steadily, so spread packets out rather than bursting
    owed = 0.0
    ticks = 0
    start = time.monotonic()
    try:
        while not cfg.duration or time.monotonic() - start < cfg.duration:
            elapsed = time.monotonic() - start
            moving = cfg.signal == "moving" or (
                cfg.signal == "mixed" and int(elapsed // cfg.period) % 2 == 1
            )
            owed += cfg.rate * tick
            n = int(owed)
            owed -= n
            for i in range(n):
                t = time.time() + i / cfg.rate
                for node in nodes:
                    pkt = node.packet(t, moving, cfg.channel)
                    if cfg.bad_kinds and rng.random() < cfg.bad_rate:
                        # Bad packets are extra; they don't use up a seq number.
                        kind = rng.choice(cfg.bad_kinds)
                        bad = make_bad(pkt, kind, rng)
                        sink.send(node.node_id, bad if isinstance(bad, bytes) else json.dumps(bad).encode())
                        counters.bad[kind] += 1
                        counters.bad_by_node[blamed_node(bad)] += 1
                    if rng.random() < cfg.skip_rate:
                        counters.skipped[node.node_id].append(pkt["seq"])
                        continue
                    sink.send(node.node_id, json.dumps(pkt).encode())
                    counters.sent[node.node_id] += 1
                    if on_valid:
                        on_valid(pkt)
            sink.flush()

            ticks += 1
            if cfg.progress and ticks % 50 == 0:
                print(f"\r{elapsed:7.1f}s  sent={sum(counters.sent.values())}  "
                      f"skipped={sum(map(len, counters.skipped.values()))}  bad={sum(counters.bad.values())}  "
                      f"{'MOVING' if moving else 'empty '}", end="", file=sys.stderr)
            time.sleep(max(0.0, start + ticks * tick - time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        sink.close()
        if cfg.progress:
            print(file=sys.stderr)
    return counters


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nodes", type=int, default=2, choices=range(1, MAX_NODES + 1), help="fake receivers (1-4)")
    ap.add_argument("--rate", type=float, default=100, help="packets per second per node")
    ap.add_argument("--duration", type=float, default=0, help="seconds to run (0 = forever)")
    ap.add_argument("--signal", choices=["empty", "moving", "mixed"], default="empty")
    ap.add_argument("--period", type=float, default=10, help="seconds per phase for --signal mixed")
    ap.add_argument("--transport", choices=list(SINKS), default="udp")
    ap.add_argument("--host", default="127.0.0.1", help="backend (udp) or broker (mqtt) host")
    ap.add_argument("--udp-port", type=int, default=5005)
    ap.add_argument("--mqtt-port", type=int, default=1883)
    ap.add_argument("--mqtt-topic", default="wavehome/csi", help="packets go to <topic>/<node_id>")
    ap.add_argument("--http-url", default="http://127.0.0.1:8000")
    ap.add_argument("--skip-rate", type=float, default=0.0, help="fraction of seq numbers never sent")
    ap.add_argument("--bad-rate", type=float, default=0.0, help="fraction of extra invalid packets")
    ap.add_argument("--bad-kinds", default=",".join(BAD_KINDS), help=f"comma list from: {', '.join(BAD_KINDS)}")
    ap.add_argument("--channel", type=int, default=6)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    kinds = [k for k in args.bad_kinds.split(",") if k]
    unknown = set(kinds) - set(BAD_KINDS)
    if unknown:
        ap.error(f"unknown --bad-kinds: {', '.join(sorted(unknown))}")

    cfg = Config(
        nodes=args.nodes, rate=args.rate, duration=args.duration, signal=args.signal, period=args.period,
        transport=args.transport, host=args.host, udp_port=args.udp_port, mqtt_port=args.mqtt_port,
        mqtt_topic=args.mqtt_topic, http_url=args.http_url, skip_rate=args.skip_rate,
        bad_rate=args.bad_rate, bad_kinds=kinds, channel=args.channel, seed=args.seed,
        progress=args.transport != "stdout",
    )
    c = run(cfg)
    print(f"done: sent={sum(c.sent.values())} skipped={sum(map(len, c.skipped.values()))} "
          f"bad={sum(c.bad.values())} {dict(c.bad)}", file=sys.stderr)


if __name__ == "__main__":
    main()
