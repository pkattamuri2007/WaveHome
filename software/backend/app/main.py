"""WaveHome ingestion API.

Run from software/backend:
    uvicorn app.main:app --reload
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
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
    return {"status": "ok", "schema_version": SCHEMA_VERSION, **store.health_snapshot()}


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
    return store.node_snapshot()


@app.post("/session")
def new_session(req: SessionRequest):
    """Start a new recording session (new folder of CSVs, fresh node stats)."""
    return {"session": store.start_session(req.name)}


@app.get("/packets/recent")
def recent_packets(
    node_id: str | None = Query(default=None, min_length=1),
    after_cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=2000),
    session_id: str | None = Query(default=None, min_length=1),
):
    """Poll in ingestion order; pass next_cursor and session_id on the next request."""
    try:
        return store.recent(node_id, after_cursor, limit, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
