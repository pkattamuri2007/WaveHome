"""Live per-node ingest statistics, served at /stats."""

import time
from collections import deque
from dataclasses import dataclass, field

from .schema import CSIPacket

RATE_WINDOW_S = 5.0
MAX_NODES = 64  # cap so junk node_ids in bad packets can't grow the table without bound
UNKNOWN_NODE = "unknown"  # rejected packets with no usable node_id


@dataclass
class NodeStats:
    accepted: int = 0
    rejected: int = 0
    dropped: int = 0          # gaps in seq, i.e. packets we never received
    out_of_order: int = 0     # seq lower than or equal to the highest one seen
    last_seq: int | None = None
    last_rssi: int | None = None
    last_seen_us: int | None = None
    first_seen: float | None = None  # monotonic seconds
    arrivals: deque = field(default_factory=deque, repr=False)  # monotonic times in the rate window

    def trim(self, now: float) -> None:
        while self.arrivals and self.arrivals[0] < now - RATE_WINDOW_S:
            self.arrivals.popleft()

    def rate_hz(self, now: float) -> float:
        self.trim(now)
        if not self.arrivals:
            return 0.0
        # A node that just started hasn't filled the window yet.
        span = max(1.0, min(RATE_WINDOW_S, now - self.first_seen))
        return len(self.arrivals) / span


class Stats:
    def __init__(self):
        self.nodes: dict[str, NodeStats] = {}
        self.recent_rejections: deque = deque(maxlen=20)

    def _node(self, node_id: str) -> NodeStats:
        if node_id not in self.nodes and len(self.nodes) >= MAX_NODES:
            node_id = UNKNOWN_NODE
        return self.nodes.setdefault(node_id, NodeStats())

    def accepted(self, p: CSIPacket, now: float, now_us: int) -> None:
        s = self._node(p.node_id)
        if s.last_seq is not None:
            if p.seq > s.last_seq + 1:
                s.dropped += p.seq - s.last_seq - 1
            elif p.seq <= s.last_seq:
                s.out_of_order += 1
        s.accepted += 1
        s.last_seq = p.seq if s.last_seq is None else max(s.last_seq, p.seq)
        s.last_rssi = p.rssi
        s.last_seen_us = now_us
        if s.first_seen is None:
            s.first_seen = now
        s.arrivals.append(now)
        s.trim(now)

    def rejected(self, node_id: str, transport: str, reason: str, now_us: int) -> None:
        self._node(node_id).rejected += 1
        self.recent_rejections.append(
            {"node_id": node_id, "transport": transport, "reason": reason, "at_us": now_us}
        )

    def snapshot(self) -> dict:
        now = time.monotonic()
        nodes = {}
        for node_id, s in self.nodes.items():
            expected = s.accepted + s.dropped
            nodes[node_id] = {
                "rate_hz": round(s.rate_hz(now), 1),
                "accepted": s.accepted,
                "rejected": s.rejected,
                "dropped": s.dropped,
                "out_of_order": s.out_of_order,
                "loss_pct": round(100 * s.dropped / expected, 2) if expected else 0.0,
                "last_seq": s.last_seq,
                "last_rssi": s.last_rssi,
                "last_seen_us": s.last_seen_us,
            }
        totals = {k: sum(n[k] for n in nodes.values()) for k in ("accepted", "rejected", "dropped")}
        return {"nodes": nodes, "totals": totals, "recent_rejections": list(self.recent_rejections)}
