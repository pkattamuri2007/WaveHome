# WaveHome

WiFi sensing for presence, motion, and zone-level tracking using Channel State Information (CSI) from ESP32-S3 boards. No cameras or wearables.

## Layout

| Path | Owner | Contents |
|---|---|---|
| `docs/schema.md` | HW2 + SW1 | Packet format shared by hardware and software |
| `hardware/` | HW1-3 | Firmware, transport, physical setup |
| `software/backend/` | SW1 | Ingestion API, storage, fake-data generator |
| `software/processing/` | SW2 | Signal processing and detection |
| `software/dashboard/` | SW3 | Live dashboard and labeling tool |

## Quick start (no hardware needed)

See [`software/backend/DOCUMENTATION.md`](software/backend/DOCUMENTATION.md) to run the API and stream fake CSI into it.
