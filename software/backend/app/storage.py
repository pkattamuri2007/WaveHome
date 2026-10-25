"""Raw CSI storage and per-node health tracking.

Packets are appended to one CSV per node per session under DATA_DIR:
    data/<session>/<node_id>.csv
The csi column holds the raw interleaved values separated by spaces.
"""

import csv
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .schema import CSIPacket

CSV_COLUMNS = [
    "ts_server_us", "node_id", "seq", "ts_device_us",
    "rssi", "channel", "bandwidth_mhz", "csi_len", "csi",
]

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]")


def _safe(name: str) -> str:
    # node_id and session come from the network; keep them out of path traversal.
    return _SAFE_NAME.sub("_", name)[:64] or "_"


@dataclass
class NodeStats:
    packets: int = 0
    dropped: int = 0          # gaps in seq, i.e. packets we never received
    out_of_order: int = 0     # seq lower than or equal to the last one seen
    last_seq: int | None = None
    last_rssi: int | None = None
    last_seen_us: int | None = None


@dataclass
class Store:
    data_dir: Path
    session: str = field(default_factory=lambda: time.strftime("%Y%m%d-%H%M%S"))
    nodes: dict[str, NodeStats] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def session_dir(self) -> Path:
        return self.data_dir / _safe(self.session)

    def start_session(self, name: str | None = None) -> str:
        with self._lock:
            self.session = _safe(name) if name else time.strftime("%Y%m%d-%H%M%S")
            self.nodes = {}
        return self.session

    def add(self, packets: list[CSIPacket]) -> None:
        now_us = time.time_ns() // 1000
        with self._lock:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            by_node: dict[str, list[CSIPacket]] = {}
            for p in packets:
                by_node.setdefault(p.node_id, []).append(p)
                self._update_stats(p, now_us)
            for node_id, rows in by_node.items():
                self._append_csv(node_id, rows, now_us)

    def _update_stats(self, p: CSIPacket, now_us: int) -> None:
        s = self.nodes.setdefault(p.node_id, NodeStats())
        if s.last_seq is not None:
            if p.seq > s.last_seq + 1:
                s.dropped += p.seq - s.last_seq - 1
            elif p.seq <= s.last_seq:
                s.out_of_order += 1
        s.packets += 1
        s.last_seq = p.seq if s.last_seq is None else max(s.last_seq, p.seq)
        s.last_rssi = p.rssi
        s.last_seen_us = now_us

    def _append_csv(self, node_id: str, rows: list[CSIPacket], now_us: int) -> None:
        path = self.session_dir / f"{_safe(node_id)}.csv"
        new_file = not path.exists()
        with path.open("a", newline="") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(CSV_COLUMNS)
            for p in rows:
                w.writerow([
                    now_us, p.node_id, p.seq, p.ts_device_us,
                    p.rssi, p.channel, p.bandwidth_mhz, p.csi_len,
                    " ".join(map(str, p.csi)),
                ])
