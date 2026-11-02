"""Bounded time-window variance and intentional empty-room calibration."""
from collections import deque
from bisect import insort_right
import math
import numpy as np


class MotionDetector:
    def __init__(self, window_seconds=2.0, threshold=None, *, min_samples=10,
                 max_samples=10000, confirmation=3, hysteresis=0.8):
        if (not math.isfinite(window_seconds) or window_seconds <= 0
                or min_samples < 2 or max_samples < min_samples or confirmation < 1
                or not 0 < hysteresis <= 1):
            raise ValueError("Invalid detector configuration")
        self.window_seconds = window_seconds
        self.min_samples = min_samples
        self.max_samples = max_samples
        self.confirmation = confirmation
        self.hysteresis = hysteresis
        self.threshold = None
        self.set_threshold(threshold)
        self.reset()

    def set_threshold(self, threshold):
        if threshold is not None and (not math.isfinite(threshold) or threshold <= 0):
            raise ValueError("threshold must be finite and positive")
        self.threshold = threshold

    def reset(self):
        self.samples = deque(maxlen=self.max_samples)
        self.ids = deque()
        self.seen = set()
        self.last_timestamp = None
        self.variance = 0.0
        self.status = "NO DATA"
        self.pending = None
        self.count = 0
        self.calibration = None
        self.baseline = None

    def start_calibration(self, duration=9.0, multiplier=5.0, minimum=0.01):
        if (not all(math.isfinite(x) for x in (duration, multiplier, minimum))
                or duration <= self.window_seconds or multiplier < 1 or minimum <= 0):
            raise ValueError("Calibration duration must exceed window; multiplier >= 1 and minimum > 0")
        self.reset()
        self.threshold = None
        self.calibration = dict(duration=duration, multiplier=multiplier, minimum=minimum,
                                start=None, variances=deque(maxlen=self.max_samples))
        self.status = "CALIBRATING"

    def result(self):
        progress = 0.0
        if self.calibration and self.calibration["start"] is not None:
            progress = min(1.0, (self.last_timestamp - self.calibration["start"]) /
                           self.calibration["duration"])
        return dict(status=self.status, variance=self.variance, threshold=self.threshold,
                    baseline=self.baseline, progress=progress)

    def update(self, timestamp, amplitude, packet_id=None):
        if not math.isfinite(timestamp) or not math.isfinite(amplitude):
            raise ValueError("Timestamp and amplitude must be finite")
        if packet_id is not None and packet_id in self.seen:
            return self.result()
        if self.last_timestamp is not None and timestamp < self.last_timestamp - self.window_seconds:
            raise ValueError("Timestamp moved backwards; reset source before processing")
        if self.last_timestamp is not None and timestamp - self.last_timestamp > self.window_seconds:
            self.samples.clear()
            self.pending, self.count = None, 0
            if self.calibration:
                self.calibration["start"] = None
                self.calibration["variances"].clear()
        self.last_timestamp = max(timestamp, self.last_timestamp) if self.last_timestamp is not None else timestamp
        if packet_id is not None:
            self.ids.append(packet_id)
            self.seen.add(packet_id)
            if len(self.ids) > self.max_samples:
                self.seen.discard(self.ids.popleft())
        if len(self.samples) == self.max_samples:
            self.samples.popleft()
        insort_right(self.samples, (timestamp, amplitude))
        timestamp = self.last_timestamp
        while self.samples and self.samples[0][0] < timestamp - self.window_seconds:
            self.samples.popleft()
        self.variance = float(np.var([x[1] for x in self.samples]))
        ready = (len(self.samples) >= self.min_samples and
                 timestamp - self.samples[0][0] >= self.window_seconds * 0.9)
        if self.calibration:
            cal = self.calibration
            if cal["start"] is None:
                cal["start"] = timestamp
            if ready:
                cal["variances"].append(self.variance)
            self.status = "CALIBRATING"
            if timestamp - cal["start"] >= cal["duration"] and cal["variances"]:
                self.baseline = float(np.percentile(cal["variances"], 95))
                self.threshold = max(cal["minimum"], self.baseline * cal["multiplier"])
                self.calibration = None
                self.status = "STILL"
            return self.result()
        if not ready:
            self.status = "NO DATA"
        elif self.threshold is None:
            self.status = "UNCALIBRATED"
        else:
            cutoff = self.threshold * (self.hysteresis if self.status == "MOVING" else 1)
            candidate = "MOVING" if self.variance > cutoff else "STILL"
            self.count = self.count + 1 if candidate == self.pending else 1
            self.pending = candidate
            if self.count >= self.confirmation:
                self.status = candidate
        return self.result()
