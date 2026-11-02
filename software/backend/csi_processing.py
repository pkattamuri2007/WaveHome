"""Amplitude features only; raw packets are never modified."""
import numpy as np


def amplitudes(csi, *, exclude_zeros=False):
    """Keep null carriers by default; no hardware-specific index assumptions."""
    try:
        values = np.asarray(csi, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("CSI must be a numeric vector") from exc
    if values.ndim != 1 or not values.size or values.size % 2:
        raise ValueError("CSI must contain a nonempty even number of I/Q values")
    if not np.isfinite(values).all():
        raise ValueError("CSI values must be finite")
    result = np.hypot(values[::2], values[1::2])
    return result[result != 0] if exclude_zeros else result


def packet_amplitude(packet, *, exclude_zeros=False):
    """Return mean amplitude; raise ValueError for an unusable packet."""
    if not isinstance(packet, dict) or "csi" not in packet:
        raise ValueError("Packet is missing CSI")
    if not isinstance(packet["csi"], (list, tuple)):
        raise ValueError("CSI must be a numeric vector")
    if packet.get("csi_len") != len(packet["csi"]):
        raise ValueError("CSI length mismatch")
    values = amplitudes(packet["csi"], exclude_zeros=exclude_zeros)
    if not values.size:
        raise ValueError("No subcarriers remain after filtering")
    return float(values.mean())


# Public helpers retained from the original CSV amplitude reader.
def calculate_amplitudes(csi_values):
    """Convert interleaved I/Q to amplitudes, preserving the original list API."""
    return amplitudes(csi_values).tolist()


def read_csi_file(filename):
    """Read CSV amplitudes using device timestamps, preserving the original API."""
    import csv
    timestamps, means = [], []
    with open(filename, newline="") as source:
        for row in csv.DictReader(source):
            values = [int(value) for value in row["csi"].split()]
            mean = float(amplitudes(values).mean())
            timestamps.append(int(row["ts_device_us"]) / 1_000_000)
            means.append(mean)
    return timestamps, means
