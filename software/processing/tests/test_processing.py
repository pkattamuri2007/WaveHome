import math
import random
import pytest
from csi_processing import amplitudes, packet_amplitude
from motion_detector import MotionDetector
from fake_sender import FakeNode


def test_amplitudes():
    assert amplitudes([12, -7, 3, 9]).tolist() == pytest.approx([math.sqrt(193), math.sqrt(90)])
    assert amplitudes([0, 0]).tolist() == [0]
    assert len(amplitudes([0, 0, -3, -4], exclude_zeros=True)) == 1
    assert amplitudes([-3, -4]).tolist() == [5]
    for invalid in ([1], [], [float("nan"), 0], None):
        with pytest.raises(ValueError):
            amplitudes(invalid)
    with pytest.raises(ValueError):
        packet_amplitude({})


def test_window_duplicates_gaps_reset():
    detector = MotionDetector(threshold=0.05)
    assert detector.update(0, 1, 0)["status"] == "NO DATA"
    for i in range(1, 110):
        detector.update(i / 50, 1, i)
    assert detector.status == "STILL"
    count = len(detector.samples)
    detector.update(2.18, 1000, 109)
    assert len(detector.samples) == count
    assert detector.variance == 0
    assert detector.update(10, 1, 110)["status"] == "NO DATA"
    with pytest.raises(ValueError):
        detector.update(7, 1)
    detector.reset()
    assert not detector.samples and not detector.seen


def test_synthetic_calibration_and_transitions():
    node = FakeNode("rx1", random.Random(7))
    detector = MotionDetector()
    detector.start_calibration(9)
    states = {}
    for i in range(1500):
        t = i / 50
        result = detector.update(t, packet_amplitude(node.packet(t, 10 <= t < 20, 6)), i)
        states[i] = result["status"]
    assert states[475] == "STILL"
    assert states[650] == "MOVING"
    assert states[1200] == "STILL"
    assert detector.baseline > 0
    assert detector.threshold == pytest.approx(max(0.01, detector.baseline * 5))
    assert len(detector.samples) <= 101


def test_irregular_timestamps_and_uncalibrated():
    detector = MotionDetector(min_samples=3)
    for timestamp in (0, .2, .9, 1.85, 2):
        detector.update(timestamp, 1)
    assert detector.status == "UNCALIBRATED"
    detector.start_calibration(8)
    detector.update(3, 1)
    detector.update(20, 1)
    assert detector.result()["progress"] == 0


def test_replay_packet_compatibility():
    import numpy as np
    from replay_csi import packet_from_row
    from app.schema import CSIPacket
    packet = packet_from_row(np.array([3 + 4j, -5 + 12j]), 0, 50, "esp32", {})
    CSIPacket(**packet)
    assert packet_amplitude(packet) == 9


def test_calibration_uses_window_distribution():
    import numpy as np
    detector = MotionDetector(window_seconds=1, min_samples=3)
    detector.start_calibration(3, multiplier=2, minimum=0.001)
    baseline_windows = []
    for i in range(31):
        t = i / 10
        amplitude = 1 + (0.2 if i % 2 else -0.2)
        window = [(j / 10, 1 + (0.2 if j % 2 else -0.2))
                  for j in range(i + 1) if j / 10 >= t - 1]
        if len(window) >= 3 and t - window[0][0] >= 0.9:
            baseline_windows.append(float(np.var([x[1] for x in window])))
        detector.update(t, amplitude, i)
    assert detector.baseline == pytest.approx(np.percentile(baseline_windows, 95))
    assert detector.threshold == pytest.approx(2 * detector.baseline)


def test_small_timestamp_reversal_is_ordered():
    detector = MotionDetector(threshold=0.05)
    for i in range(110):
        detector.update(i / 50, 1, i)
    detector.update(2.17, 1, 111)
    assert detector.status == "STILL"
    assert list(detector.samples) == sorted(detector.samples)
    assert detector.last_timestamp == 2.18
