"""Replay recorded ESP32 CSI samples into the WaveHome FastAPI ingestion API.

Run from software/backend after installing requirements (including numpy):
    python replay_csi.py --dataset /path/to/RF_ESP32_Dataset-v1.0.1.zip --list
    python replay_csi.py --dataset /path/to/RF_ESP32_Dataset-v1.0.1.zip --dry-run
    python replay_csi.py --dataset /path/to/RF_ESP32_Dataset-v1.0.1.zip --rate 50

Reads the nested 01_human_activity.zip directly; no manual extraction needed.
NOTE: Packet timestamps are synthetic replay timestamps, NOT original capture timing.
Each 2D-array row is treated as one replayable CSI sample (not necessarily a
consecutive raw radio packet). Activity labels are session metadata, not packet labels.
"""

import argparse
import io
import json
import time
import zipfile
from pathlib import Path

import httpx
import numpy as np

INNER_ZIP_NAME = '01_human_activity.zip'


def open_human_activity_zip(dataset_path: Path) -> zipfile.ZipFile:
    """Return inner human-activity ZIP, or use a directly supplied inner ZIP."""
    with zipfile.ZipFile(dataset_path) as outer:
        path = next((name for name in outer.namelist()
                     if name.endswith('/' + INNER_ZIP_NAME)), None)
        if path is None:
            if any(name.endswith('/csi_data.npy') for name in outer.namelist()):
                return zipfile.ZipFile(io.BytesIO(dataset_path.read_bytes()))
            raise ValueError('Could not find 01_human_activity.zip or CSI sessions')
        return zipfile.ZipFile(io.BytesIO(outer.read(path)))


def sessions_in(archive: zipfile.ZipFile) -> list[str]:
    return sorted(name.rsplit('/', 1)[0] for name in archive.namelist()
                  if name.endswith('/csi_data.npy'))


def select_session(sessions: list[str], requested: str | None) -> str:
    if not sessions:
        raise ValueError('No csi_data.npy sessions found')
    if requested is None:
        return sessions[0]
    matches = [s for s in sessions if s == requested or s.endswith('/' + requested)]
    if len(matches) != 1:
        raise ValueError(f'Session {requested!r} matched {len(matches)} sessions; run --list')
    return matches[0]


def load_session(archive: zipfile.ZipFile, session: str):
    csi = np.load(io.BytesIO(archive.read(session + '/csi_data.npy')), allow_pickle=False)
    if csi.ndim != 2 or not np.iscomplexobj(csi):
        raise ValueError(f'Expected 2D complex CSI, got shape={csi.shape}, dtype={csi.dtype}')
    if not np.isfinite(csi.real).all() or not np.isfinite(csi.imag).all():
        raise ValueError('Nonfinite CSI measurements found')
    metadata = json.loads(archive.read(session + '/metadata.json'))
    if not isinstance(metadata, list):
        raise ValueError('Expected metadata.json to contain a list')
    return csi, metadata


def packet_from_row(row, seq: int, rate: float, node_id: str, rf: dict) -> dict:
    """Produce [real0, imag0, real1, imag1, ...], enforcing signed int8 bounds."""
    interleaved = np.empty(row.size * 2, dtype=np.float64)
    interleaved[::2] = row.real
    interleaved[1::2] = row.imag
    if np.any((interleaved < -128) | (interleaved > 127)):
        raise ValueError(f'CSI value outside [-128, 127] in replay row {seq}; refusing to clip')
    if not np.all(interleaved == np.rint(interleaved)):
        raise ValueError(f'CSI value is not integral in replay row {seq}')
    csi = interleaved.astype(int).tolist()
    # ESP32 bandwidth: 0 -> 20 MHz, 1 -> 40 MHz.
    bandwidth_flag = int(rf.get('bandwidth', 0))
    if bandwidth_flag not in (0, 1):
        raise ValueError(f'Unknown ESP32 bandwidth flag: {bandwidth_flag}')
    return {
        'schema_version': '0.1',
        'node_id': node_id,
        'seq': seq,
        'ts_device_us': round(seq * 1_000_000 / rate),
        'rssi': int(rf.get('rssi', -50)),
        'channel': int(rf.get('channel', 1)),
        'bandwidth_mhz': 40 if bandwidth_flag == 1 else 20,
        'csi_len': len(csi),
        'csi': csi,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dataset', required=True, type=Path, help='Outer dataset ZIP or 01_human_activity.zip')
    parser.add_argument('--list', action='store_true', help='List recording sessions then exit')
    parser.add_argument('--session', help='Session name, e.g. session_20260118_224110 (default: first)')
    parser.add_argument('--url', default='http://127.0.0.1:8000', help='WaveHome backend base URL')
    parser.add_argument('--rate', type=float, default=50.0, help='Replay rows/second (synthetic timing)')
    parser.add_argument('--batch-size', type=int, default=10, help='Packets per POST')
    parser.add_argument('--limit', type=int, help='Maximum CSI rows to replay')
    parser.add_argument('--node-id', default='esp32-demo', help='Node ID for replayed packets')
    parser.add_argument('--dry-run', action='store_true', help='Validate/preview packets without sending')
    args = parser.parse_args()

    if args.rate <= 0 or args.batch_size <= 0 or (args.limit is not None and args.limit <= 0):
        parser.error('--rate, --batch-size and --limit (when specified) must be positive')
    if not args.dataset.is_file():
        parser.error(f'Dataset not found: {args.dataset}')

    with open_human_activity_zip(args.dataset) as archive:
        sessions = sessions_in(archive)
        if args.list:
            for s in sessions:
                print(s.split('/')[-1])
            print(f'Total sessions: {len(sessions)}')
            return
        session = select_session(sessions, args.session)
        csi, metadata = load_session(archive, session)

    rf = (metadata[0].get('rf_parameters') or {}) if metadata else {}
    count = min(len(csi), args.limit) if args.limit else len(csi)
    # Validate before sending anything so an invalid sample does not partly replay.
    packets = [packet_from_row(csi[i], i, args.rate, args.node_id, rf) for i in range(count)]
    print(f'Session: {session.split("/")[-1]} | CSI array: {csi.shape} | replay rows: {count}')
    print(f'Activity examples: {sorted({m.get("activity", "unknown") for m in metadata})}')
    print(f'First packet: node={packets[0]["node_id"]}, csi_len={packets[0]["csi_len"]}, '
          f'rssi={packets[0]["rssi"]}, channel={packets[0]["channel"]}, '
          f'bandwidth={packets[0]["bandwidth_mhz"]} MHz')
    if args.dry_run:
        print('Dry run: all packets prepared; nothing sent.')
        return

    print(f'Sending to {args.url.rstrip("/")}/ingest/batch at ~{args.rate:g} packets/sec')
    sent = 0
    started = time.monotonic()
    with httpx.Client(timeout=15.0) as client:
        for start in range(0, count, args.batch_size):
            batch = packets[start:start + args.batch_size]
            response = client.post(args.url.rstrip('/') + '/ingest/batch', json=batch)
            response.raise_for_status()
            accepted = response.json().get('accepted')
            if accepted != len(batch):
                raise RuntimeError(f'Sent {len(batch)} packets but server accepted {accepted}')
            sent += accepted
            # Pace based on cumulative send count to reduce drift. Approximate speed only.
            remaining = started + sent / args.rate - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
        print(f'Finished: accepted {sent}/{count} packets')
        print('Node stats:', client.get(args.url.rstrip('/') + '/stats').json()['nodes'])


if __name__ == '__main__':
    main()
