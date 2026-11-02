# Live CSI dashboard (Python 3.11, macOS)

Run these commands from the repository root, in separate terminal tabs where
indicated. Activate the same environment in every tab.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r software/dashboard/requirements.txt
python -m uvicorn app.main:app --app-dir software/backend --host 127.0.0.1 --port 8000
```

Dashboard terminal:

```bash
source .venv/bin/activate
python -m streamlit run software/backend/live_dashboard.py
```

Open http://localhost:8501. Select the receiver. Start a synthetic empty source,
then click **Calibrate Empty Room** and keep the source empty for nine seconds:

```bash
source .venv/bin/activate
python software/backend/fake_sender.py --nodes 1 --scenario empty --rate 50
```

Stop that sender after calibration. For a single continuous demonstration instead,
start the following sender and click calibration immediately during its first
empty interval (calibration must finish before the ten-second boundary):

```bash
python software/backend/fake_sender.py --nodes 1 --scenario mixed --duration 30 --rate 50 --seed 7
```

Use `--period 15 --duration 45` to allow more time for manual calibration.
Calibration of synthetic data is demonstration-only. A new sender may restart
its device clock: the dashboard resets calibration on backwards timestamps.
For consistent hardware demonstrations, calibrate and detect on one continuous
source without changing RF geometry, rate, carrier filtering, or node.

## Data flow

Generator / ESP32 replayer → unchanged v0.1 ingestion → CSV and bounded recent
buffer → HTTP polling every 0.25 seconds → amplitude → per-source detector →
Streamlit metrics and bounded chart.

The UI keeps one active receiver detector; changing receiver, URL, zero-carrier
policy, or session discards calibration. No receivers are mixed. Device timestamps
drive the signal window, including replay's synthetic timestamps; server times
record arrival only. Backwards device timestamps beyond the two-second window reset processing;
late measurements within the current window are ordered by timestamp. A gap longer
than the window restarts warmup (and an in-progress calibration); no data received
for three wall-clock seconds displays NO DATA. Connection failures are shown and
polling retries automatically. Calibration survives a short connection interruption
only if the session and retained data remain continuous.

## Recent-packet API

`GET /packets/recent?node_id=rx1&after_cursor=0&limit=200&session_id=...`

Returns `session`, unique `session_id`, `packets` (each containing `cursor`,
`ts_server_us`, and unchanged `packet`), `next_cursor`, `latest_cursor`,
`oldest_cursor`, `has_more`, `gap`, and `reset`.
Pass next_cursor and session_id on subsequent polls; drain pages while has_more.
Use latest_cursor to intentionally start collecting future packets only.
Sequence numbers are not retrieval cursors. Each accepted ingestion has its own
cursor even when packet sequence numbers repeat. Repeated polling does not process
a cursor twice; retransmitted packets accepted separately are distinct ingestions.

The default buffer holds 20,000 packets across all receivers (about 400 seconds at
50 packets/second for one receiver); storage is still CSV. Capacity is configurable
on Store construction. Old packets are evicted, never recovered from disk by this
endpoint. A nonzero cursor older than retained history sets gap=true; the UI resets
calibration. An initial cursor of zero requests retained history. A changed
session_id ignores the stale cursor and sets reset=true, including after process
restart or reuse of the same session name. Cursors increase for the lifetime of
one process; session IDs identify restarts. Limits are 1–2000; invalid query
parameters return HTTP 422. A cursor ahead of the server returns HTTP 409;
provide the previous session_id so a restarted server can reset it safely. Run one backend worker: separate processes would
have separate buffers and session state. Existing CSV append semantics remain.

## Real ESP32 replay

```bash
python software/backend/replay_csi.py --dataset /absolute/path/RF_ESP32_Dataset-v1.0.1.zip --list
python software/backend/replay_csi.py --dataset /absolute/path/RF_ESP32_Dataset-v1.0.1.zip --session SESSION_NAME --dry-run
python software/backend/replay_csi.py --dataset /absolute/path/RF_ESP32_Dataset-v1.0.1.zip --session SESSION_NAME --rate 50 --node-id esp32-demo
```

Explicitly select a recording whose metadata establishes an empty room before
using the calibration button during replay. Human activity categories alone are
not evidence of emptiness. If no verified baseline exists, leave the detector
UNCALIBRATED or demonstrate with synthetic data. No real-data accuracy is claimed.
The replayer and packet schema have not been changed.

## Tests and troubleshooting

```bash
python -m pytest -q
```

If no nodes appear, check /health and /nodes at http://127.0.0.1:8000,
the sender URL, and sender acceptance counts. If the backend is unavailable,
check the process and dashboard Backend URL. Odd-length, missing, nonfinite,
or unusable CSI is skipped with a visible count; inspect the source.
If calibration stalls, keep packets arriving for the full duration with no
gaps longer than two seconds. If a device clock resets or the buffer overruns,
recalibrate. Increase calibration duration or inspect the amplitude plot if
motion flickers; do not treat a synthetic threshold as a universal hardware value.
A two-second window naturally delays motion clearing. Motion variance does not
prove occupancy or room location.
