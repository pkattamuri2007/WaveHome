"""Raw CSI storage.

Packets are appended to one CSV per node per session under the data directory:
    data/<session>/<node_id>.csv
The csi column holds the raw interleaved values separated by spaces.
Use load_session() to read a session back.
"""

import csv
import re
from pathlib import Path

from .schema import CSIPacket

CSV_COLUMNS = [
    "ts_server_us", "node_id", "seq", "ts_device_us",
    "rssi", "channel", "bandwidth_mhz", "csi_len", "csi",
]
INT_COLUMNS = ["ts_server_us", "seq", "ts_device_us", "rssi", "channel", "bandwidth_mhz", "csi_len"]

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]")


def safe_name(name: str) -> str:
    # node_id and session come from the network; keep them out of path traversal.
    return _SAFE_NAME.sub("_", name)[:64].lstrip(".") or "_"


class CsvWriter:
    """Keeps one open file per node so high packet rates don't reopen files on every packet."""

    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self._files: dict[str, tuple] = {}

    def write(self, packets: list[CSIPacket], ts_server_us: int) -> None:
        touched = set()
        for p in packets:
            f, w = self._open(p.node_id)
            w.writerow([
                ts_server_us, p.node_id, p.seq, p.ts_device_us,
                p.rssi, p.channel, p.bandwidth_mhz, p.csi_len,
                " ".join(map(str, p.csi)),
            ])
            touched.add(f)
        # Flush so data on disk is always complete, even if the server is killed.
        for f in touched:
            f.flush()

    def _open(self, node_id: str):
        if node_id not in self._files:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            path = self.session_dir / f"{safe_name(node_id)}.csv"
            new_file = not path.exists()
            f = path.open("a", newline="")
            w = csv.writer(f)
            if new_file:
                w.writerow(CSV_COLUMNS)
            self._files[node_id] = (f, w)
        return self._files[node_id]

    def close(self) -> None:
        for f, _ in self._files.values():
            f.close()
        self._files.clear()


def load_session(session_dir: str | Path) -> dict[str, list[dict]]:
    """Read a recorded session back as {node_id: [packet, ...]} in arrival order.

    Each packet is a dict with the CSV columns as ints and csi as a list of ints.
    """
    out: dict[str, list[dict]] = {}
    for path in sorted(Path(session_dir).glob("*.csv")):
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                pkt = {k: int(row[k]) for k in INT_COLUMNS}
                pkt["node_id"] = row["node_id"]
                pkt["csi"] = [int(v) for v in row["csi"].split()]
                out.setdefault(pkt["node_id"], []).append(pkt)
    return out
