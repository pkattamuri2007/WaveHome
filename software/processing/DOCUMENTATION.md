# Amplitude and motion processing

The existing backend/csi_processing.py is independent of Streamlit. amplitudes computes
hypot(pair[0], pair[1]) in floating point; packet_amplitude returns its mean.
The generator's imaginary/real and replayer's real/imaginary ordering yield the
same amplitude. Raw packets are never changed. Zero carriers are retained by
default; exclude_zeros is explicit, with no unverified hardware index mask.

backend/motion_detector.py contains MotionDetector, which keeps a time-based two-second deque, capped at 10,000 samples.
At least ten samples and 90% window coverage are required. It computes population
variance over the bounded current window, never recording history. The cap may
shorten coverage at extreme input rates; such windows remain unready.
A threshold can be supplied directly for tests; otherwise it stays UNCALIBRATED.
Three consecutive classifications confirm state changes, and MOVING clears below
80% of the threshold to reduce flicker. Confirmation latency depends on rate.

start_calibration explicitly discards the previous threshold. Nine seconds of
known empty input produce a distribution of warmed-up rolling variances.
Threshold = max(0.01, 5 × percentile95(rolling variances)).
Duration, multiplier and minimum are configurable through the class; the UI
exposes duration. Baseline storage is bounded to 10,000 variances. Gaps restart
calibration collection. Calibration belongs to the selected node/session and
zero-carrier policy, not an arbitrary dataset's first seconds.

Use ingestion cursors as packet_id for bounded duplicate suppression. Identical
cursor polls are ignored; separately ingested retransmissions have new cursors.
reset clears temporal and deduplication state; it preserves a manually configured
threshold. The dashboard constructs a new detector when source/session changes
so its calibration is discarded. Negative/nonfinite configuration, nonfinite
measurements and backwards timestamps beyond the window raise ValueError.
Late measurements within the current window are inserted in time order;
the window watermark never moves backwards.

See ../dashboard/DOCUMENTATION.md for launch commands, API behavior, limitations
and replay calibration guidance.

The original calculate_amplitudes and read_csi_file APIs remain available for plot_csi.py.
The detector now accepts update(timestamp, amplitude, packet_id=None) and returns a
result dictionary. The old sample-only update and implicit CSV calibration were
replaced to support explicit live calibration and irregular timing.
