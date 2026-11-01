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



## ESP32 CSI Dataset Replayer

The `replay_csi.py` script replays recorded ESP32 CSI measurements through the WaveHome FastAPI backend for development and dashboard demonstrations.

### Setup

1. Download `RF_ESP32_Dataset-v1.0.1.zip` from the project's dataset source and place it in `software/backend/`. The dataset is excluded from Git.
2. From `software/backend/`, activate your Python environment and run `python -m pip install -r requirements.txt`.
3. Start the API in one terminal: `python -m uvicorn app.main:app --reload`.

### Run

Dry run:
`python replay_csi.py --dataset RF_ESP32_Dataset-v1.0.1.zip --dry-run`

Live replay:
`python replay_csi.py --dataset RF_ESP32_Dataset-v1.0.1.zip --url http://127.0.0.1:8000 --rate 50 --batch-size 10 --limit 200`

### Verification

Check `http://127.0.0.1:8000/nodes` for received packet counts.
Check `software/backend/data/<session>/<node_id>.csv` for stored packets.

### Notes

The replayer converts complex CSI samples into interleaved signed integer real/imaginary values compatible with schema version 0.1. The replay rate is configurable and does not represent the original measurement sampling frequency. Activity labels are available in the source dataset but are not included in the ingestion packet schema.
