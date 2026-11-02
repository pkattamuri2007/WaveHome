"""Shared ingest path for every transport (UDP, MQTT, HTTP): validate, store, count."""

import json
import threading
import time
from pathlib import Path

from pydantic import ValidationError

from .schema import CSIPacket
from .stats import UNKNOWN_NODE, Stats
from .storage import CsvWriter, safe_name


def _reason(e: ValidationError) -> str:
    errors = e.errors()
    first = errors[0]
    loc = ".".join(str(x) for x in first["loc"])
    msg = f"{loc}: {first['msg']}" if loc else first["msg"]
    return msg + (f" (+{len(errors) - 1} more)" if len(errors) > 1 else "")


class Ingestor:
    def __init__(self, data_dir: Path, session: str | None = None):
        self.data_dir = Path(data_dir)
        # UDP and HTTP run on the event loop, MQTT on its own thread.
        self._lock = threading.Lock()
        self._start(session)

    def _start(self, session: str | None) -> None:
        self.session = safe_name(session) if session else time.strftime("%Y%m%d-%H%M%S")
        self.writer = CsvWriter(self.data_dir / self.session)
        self.stats = Stats()

    @property
    def session_dir(self) -> Path:
        return self.data_dir / self.session

    def new_session(self, name: str | None = None) -> str:
        """Start a new recording folder and reset stats."""
        with self._lock:
            self.writer.close()
            self._start(name)
            return self.session

    def close(self) -> None:
        with self._lock:
            self.writer.close()

    def snapshot(self) -> dict:
        with self._lock:
            return {"session": self.session, **self.stats.snapshot()}

    def handle_raw(self, raw: bytes, transport: str) -> str | None:
        """Handle one JSON-encoded packet. Returns None if accepted, else the rejection reason."""
        try:
            obj = json.loads(raw)
        except ValueError:
            return self._reject(None, transport, "invalid JSON")
        return self.handle_obj(obj, transport)

    def handle_obj(self, obj, transport: str) -> str | None:
        """Handle one decoded packet. Returns None if accepted, else the rejection reason."""
        try:
            pkt = CSIPacket.model_validate(obj)
        except ValidationError as e:
            return self._reject(obj, transport, _reason(e))
        now_us = time.time_ns() // 1000
        with self._lock:
            self.writer.write([pkt], now_us)
            self.stats.accepted(pkt, time.monotonic(), now_us)
        return None

    def _reject(self, obj, transport: str, reason: str) -> str:
        node_id = obj.get("node_id") if isinstance(obj, dict) else None
        if not isinstance(node_id, str) or not node_id:
            node_id = UNKNOWN_NODE
        with self._lock:
            self.stats.rejected(node_id[:64], transport, reason, time.time_ns() // 1000)
        return reason
