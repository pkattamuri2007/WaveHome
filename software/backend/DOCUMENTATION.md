# Backend (SW1)

Ingestion API and fake-data generator. Packets follow [`docs/schema.md`](../../docs/schema.md) (v0.1).

## Setup

```bash
cd software/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

## Run

```bash
# terminal 1: API on http://127.0.0.1:8000 (interactive docs at /docs)
.venv/bin/uvicorn app.main:app --reload

# terminal 2: fake receivers
.venv/bin/python fake_sender.py --nodes 2 --scenario mixed --drop-rate 0.01
```

`fake_sender.py --help` lists every option. `--stdout` prints JSON lines instead of sending them, which is useful for tests or for SW2 without a running server.

## Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Status, schema version, current session |
| POST | `/ingest` | One packet. 422 with the reason if invalid |
| POST | `/ingest/batch` | List of packets. Rejected as a whole if any packet is invalid |
| GET | `/nodes` | Per-node packets, dropped (seq gaps), out-of-order, loss %, last RSSI |
| POST | `/session` | `{"name": "walk-zone-a"}` starts a new recording folder and resets node stats |

## Validation

Beyond the JSON Schema in `docs/schema.md`, the backend also:
- rejects `csi_len` that does not match the length of `csi`
- rejects `schema_version` other than `"0.1"`
- uses strict types, so `"5"` or `5.0` are not accepted as integers
- ignores extra unknown fields

## Storage

Raw packets go to `data/<session>/<node_id>.csv` (override the root with `WAVEHOME_DATA_DIR`). Columns: `ts_server_us, node_id, seq, ts_device_us, rssi, channel, bandwidth_mhz, csi_len, csi`, where `csi` is the raw interleaved values separated by spaces (imaginary, real per subcarrier).

## Not done yet

- Session metadata database (labels, notes)
- Parquet output
- UDP/MQTT listener (HTTP only for now)
- Live stream to the dashboard (WebSocket)
