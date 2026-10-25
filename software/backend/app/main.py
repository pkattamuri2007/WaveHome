"""WaveHome ingestion API.

Run from software/backend:
    uvicorn app.main:app --reload
"""

import os
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from .schema import SCHEMA_VERSION, CSIPacket
from .storage import Store

DATA_DIR = Path(os.environ.get("WAVEHOME_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))

app = FastAPI(title="WaveHome Ingestion API", version="0.1.0")
store = Store(data_dir=DATA_DIR)


class SessionRequest(BaseModel):
    name: str | None = None


@app.get("/health")
def health():
    return {"status": "ok", "schema_version": SCHEMA_VERSION, "session": store.session}


@app.post("/ingest")
def ingest(packet: CSIPacket):
    """Accept one packet. Invalid packets get a 422 with the reason."""
    store.add([packet])
    return {"accepted": 1}


@app.post("/ingest/batch")
def ingest_batch(packets: list[CSIPacket]):
    """Accept many packets at once. If any packet is invalid, the whole batch is rejected."""
    store.add(packets)
    return {"accepted": len(packets)}


@app.get("/nodes")
def nodes():
    """Per-node health: packet counts, dropped packets (from seq gaps), last RSSI."""
    return {
        node_id: {**vars(s), "loss_pct": round(100 * s.dropped / (s.packets + s.dropped), 2)}
        for node_id, s in store.nodes.items()
    }


@app.post("/session")
def new_session(req: SessionRequest):
    """Start a new recording session (new folder of CSVs, fresh node stats)."""
    return {"session": store.start_session(req.name)}
