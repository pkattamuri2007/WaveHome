"""WaveHome ingestion API.

Run from software/backend:
    uvicorn app.main:app --reload

Devices send one JSON packet per UDP datagram (port 5005) or per MQTT message.
HTTP endpoints accept the same packets for tools and tests.

Settings (environment variables):
    WAVEHOME_DATA_DIR    where sessions are saved (default software/backend/data)
    WAVEHOME_UDP_PORT    UDP listen port, or "off" (default 5005)
    WAVEHOME_MQTT_HOST   MQTT broker host; MQTT is off unless this is set
    WAVEHOME_MQTT_PORT   broker port (default 1883)
    WAVEHOME_MQTT_TOPIC  topic to subscribe to (default wavehome/csi/#)
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .ingest import Ingestor
from .schema import SCHEMA_VERSION
from .transports import start_mqtt, start_udp

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_BATCH_ERRORS = 20


class SessionRequest(BaseModel):
    name: str | None = None


def create_app(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    udp_port: int | None = 5005,
    udp_host: str = "0.0.0.0",
    mqtt_host: str | None = None,
    mqtt_port: int = 1883,
    mqtt_topic: str = "wavehome/csi/#",
) -> FastAPI:
    ingestor = Ingestor(Path(data_dir))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        udp = mqtt = None
        if udp_port is not None:
            udp = await start_udp(ingestor, udp_host, udp_port)
            app.state.udp_port = udp.get_extra_info("sockname")[1]
        if mqtt_host:
            mqtt = start_mqtt(ingestor, mqtt_host, mqtt_port, mqtt_topic)
        app.state.mqtt = mqtt
        try:
            yield
        finally:
            if udp:
                udp.close()
            if mqtt:
                mqtt.disconnect()
                mqtt.loop_stop()
            ingestor.close()

    app = FastAPI(title="WaveHome Ingestion API", version="0.2.0", lifespan=lifespan)
    app.state.ingestor = ingestor
    app.state.udp_port = None
    app.state.mqtt = None

    @app.get("/health")
    def health():
        mqtt = app.state.mqtt
        return {
            "status": "ok",
            "schema_version": SCHEMA_VERSION,
            "session": ingestor.session,
            "udp_port": app.state.udp_port,
            "mqtt": {"host": mqtt_host, "connected": mqtt.is_connected()} if mqtt else None,
        }

    @app.get("/stats")
    def stats():
        """Per-node packet rate, accepted, rejected, dropped (seq gaps), plus recent rejection reasons."""
        return ingestor.snapshot()

    @app.post("/ingest")
    async def ingest(request: Request):
        """Accept one packet. Invalid packets get a 422 with the reason and are counted as rejected."""
        reason = ingestor.handle_raw(await request.body(), "http")
        if reason:
            return JSONResponse({"accepted": 0, "rejected": 1, "reason": reason}, status_code=422)
        return {"accepted": 1, "rejected": 0}

    @app.post("/ingest/batch")
    async def ingest_batch(request: Request):
        """Accept a JSON array of packets. Each is validated on its own; bad ones are rejected and counted."""
        try:
            items = json.loads(await request.body())
        except ValueError:
            items = None
        if not isinstance(items, list):
            return JSONResponse({"detail": "body must be a JSON array of packets"}, status_code=422)
        errors = []
        for i, item in enumerate(items):
            reason = ingestor.handle_obj(item, "http")
            if reason:
                errors.append({"index": i, "reason": reason})
        return {
            "accepted": len(items) - len(errors),
            "rejected": len(errors),
            "errors": errors[:MAX_BATCH_ERRORS],
        }

    @app.post("/session")
    def new_session(req: SessionRequest):
        """Start a new recording session (new folder of CSVs, fresh stats)."""
        return {"session": ingestor.new_session(req.name)}

    return app


def _env_port(name: str, default: str) -> int | None:
    value = os.environ.get(name, default).strip().lower()
    return None if value in ("", "off", "none") else int(value)


app = create_app(
    data_dir=os.environ.get("WAVEHOME_DATA_DIR", DEFAULT_DATA_DIR),
    udp_port=_env_port("WAVEHOME_UDP_PORT", "5005"),
    mqtt_host=os.environ.get("WAVEHOME_MQTT_HOST") or None,
    mqtt_port=int(os.environ.get("WAVEHOME_MQTT_PORT", "1883")),
    mqtt_topic=os.environ.get("WAVEHOME_MQTT_TOPIC", "wavehome/csi/#"),
)
