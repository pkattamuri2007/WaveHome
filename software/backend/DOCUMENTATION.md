# Backend (SW1)

Ingestion API, fake device generator, and soak test. Packets follow [`docs/schema.md`](../../docs/schema.md) (v0.1).

## Setup

```bash
cd software/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

## Run

```bash
# terminal 1: API on http://127.0.0.1:8000 (interactive docs at /docs), UDP on port 5005
.venv/bin/uvicorn app.main:app --reload

# terminal 2: fake receivers sending over UDP like real devices
.venv/bin/python fake_sender.py --nodes 4 --signal mixed

# terminal 3: watch it
curl -s localhost:8000/stats | python3 -m json.tool
```

## How devices send data

Each packet is one JSON object (schema v0.1). Pick a transport with HW2:

| Transport | How | Backend setting |
|---|---|---|
| **UDP** (default) | One packet per datagram to `<backend-ip>:5005` | `WAVEHOME_UDP_PORT` (default `5005`, `off` to disable) |
| **MQTT** | Publish one packet per message to `wavehome/csi/<node_id>` | `WAVEHOME_MQTT_HOST` (MQTT is off unless set), `WAVEHOME_MQTT_PORT`, `WAVEHOME_MQTT_TOPIC` (default `wavehome/csi/#`) |
| HTTP | `POST /ingest` or `/ingest/batch` | always on; meant for tools and tests |

All three go through the same validation, storage, and stats.

### Running with MQTT

MQTT needs a broker. The easiest is Mosquitto in Docker:

```bash
docker run -d --rm --name wavehome-mqtt -p 1883:1883 eclipse-mosquitto:2 mosquitto -c /mosquitto-no-auth.conf
WAVEHOME_MQTT_HOST=127.0.0.1 .venv/bin/uvicorn app.main:app
.venv/bin/python fake_sender.py --transport mqtt
docker stop wavehome-mqtt   # when done
```

Without Docker: `brew install mosquitto` (macOS) or `sudo apt install mosquitto` (Linux/Pi).

## Fake data generator

`fake_sender.py --help` lists every option. The main ones:

| Option | Default | What it does |
|---|---|---|
| `--nodes` | 2 | Fake receivers, 1 to 4 (`rx1`..`rx4`) |
| `--rate` | 100 | Packets per second per node |
| `--signal` | `empty` | `empty`, `moving`, or `mixed` (alternates every `--period` seconds) |
| `--transport` | `udp` | `udp`, `mqtt`, `http`, or `stdout` (prints JSON lines) |
| `--skip-rate` | 0 | Fraction of seq numbers never sent. The backend should count these as dropped |
| `--bad-rate` | 0 | Fraction of extra invalid packets. The backend should reject and count these |
| `--bad-kinds` | all | Comma list: `missing_field`, `wrong_type`, `out_of_range`, `len_mismatch`, `not_json` |
| `--duration` | 0 | Seconds to run, 0 = until Ctrl-C |

Bad packets are sent in addition to the good ones and don't use up a seq number, so they never show up as drops.

## Soak test (deliverable check)

`soak_test.py` starts its own server on free ports, streams fake data at it, then checks:

1. the server stayed up for the whole run
2. every bad packet was rejected and counted, in total and per node
3. dropped counts match the seq numbers the generator skipped
4. stored data loads back and matches what was sent, row for row
5. per-node `rate_hz` matches the configured rate (within 10%)

```bash
.venv/bin/python soak_test.py --nodes 4 --duration 600      # the 10-minute deliverable run, over UDP
.venv/bin/python soak_test.py --duration 20                 # quick check
.venv/bin/python soak_test.py --transport mqtt --duration 60  # needs the broker running
```

It exits 0 on pass and 1 on failure, keeping the recorded data and server log for debugging when it fails.

## Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Status, schema version, session, UDP port, MQTT connection |
| GET | `/stats` | Per node: `rate_hz`, `accepted`, `rejected`, `dropped`, `out_of_order`, `loss_pct`, last seq/RSSI. Also totals and the last 20 rejection reasons |
| POST | `/ingest` | One packet. 422 with the reason if invalid |
| POST | `/ingest/batch` | JSON array of packets. Each is checked separately; returns accepted/rejected counts and the errors |
| POST | `/session` | `{"name": "walk-zone-a"}` starts a new recording folder and resets stats |

Notes on `/stats`:
- `rate_hz` is accepted packets per second over the last 5 seconds.
- `dropped` comes from gaps in `seq`. It can't see packets lost before the first or after the last one received.
- Rejected packets with no usable `node_id` (not JSON, missing or wrong-type `node_id`) are counted under `unknown`.

## Validation

Beyond the JSON Schema in `docs/schema.md`, the backend also:
- rejects `csi_len` that does not match the length of `csi`
- rejects `schema_version` other than `"0.1"`
- uses strict types, so `"5"`, `5.0` or `true` are not accepted as integers
- ignores extra unknown fields

## Storage

Raw packets go to `data/<session>/<node_id>.csv` (override the root with `WAVEHOME_DATA_DIR`). Columns: `ts_server_us, node_id, seq, ts_device_us, rssi, channel, bandwidth_mhz, csi_len, csi`, where `csi` is the raw interleaved values separated by spaces (imaginary, real per subcarrier). Each write is flushed, so files are complete even if the server is killed.

To read a session back (for example in SW2's pipeline):

```python
from app.storage import load_session
packets = load_session("data/walk-zone-a")   # {"rx1": [{"seq": 0, "csi": [...], ...}, ...], ...}
```

## Not done yet

- Session metadata database (labels, notes)
- Parquet output
- Live stream to the dashboard (WebSocket)
- Serial (USB) bridge, if HW1/HW2 go that route for v0
