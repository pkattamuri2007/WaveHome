"""Launch from repository root: python -m streamlit run software/backend/live_dashboard.py"""
import sys
import time
from collections import deque
from pathlib import Path

import httpx
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from csi_processing import packet_amplitude
from motion_detector import MotionDetector

st.set_page_config(page_title="WaveHome · Live CSI", page_icon="📡", layout="wide")
st.title("WaveHome")
st.caption("LIVE CSI MONITOR · amplitude and calibrated motion")
url = st.sidebar.text_input("Backend URL", "http://127.0.0.1:8000").rstrip("/")
visible = st.sidebar.slider("Visible seconds", 10, 30, 20)
duration = st.sidebar.slider("Empty-room calibration seconds", 8, 30, 9)
exclude_zeros = st.sidebar.checkbox("Exclude zero-amplitude carriers", False)
st.sidebar.caption("Keep the room empty throughout calibration. Dataset activity labels do not establish an empty room.")


def fresh(session_id):
    return dict(session_id=session_id, cursor=0, detector=MotionDetector(),
                history=deque(maxlen=10000), processed=0, invalid=0,
                last_seen=None, origin=None, last_device=None,
                latest=None, notice="")


@st.fragment(run_every=0.25)
def monitor():
    try:
        with httpx.Client(base_url=url, timeout=2) as client:
            health = client.get("/health")
            health.raise_for_status()
            nodes = client.get("/nodes")
            nodes.raise_for_status()
            choices = sorted(nodes.json())
            if not choices:
                st.info("NO DATA · Backend connected. Start a sender or replay.")
                return
            node = st.selectbox("Receiver", choices)
            source = (url, node, exclude_zeros)
            state = st.session_state.get("live")
            if (state is None or st.session_state.get("source") != source
                    or state["session_id"] != health.json()["session_id"]):
                state = fresh(health.json()["session_id"])
                st.session_state.live = state
                st.session_state.source = source
                state["notice"] = "Source/session changed. Calibration reset."
            st.caption(f"Connected · Recording: {health.json()['session']} · Receiver: {node}")
            left, right = st.columns([1, 3])
            with left:
                if st.button("Calibrate Empty Room", type="primary"):
                    # Start at the current tail: previously buffered data is not calibration.
                    tail = client.get("/packets/recent", params={"node_id": node, "limit": 1})
                    tail.raise_for_status()
                    state = fresh(tail.json()["session_id"])
                    state["cursor"] = tail.json()["latest_cursor"]
                    state["detector"].start_calibration(duration)
                    st.session_state.live = state
                if st.button("Reset calibration"):
                    state["detector"] = MotionDetector()
                st.caption("Keep the room empty. Calibration uses only newly ingested measurements.")
            response = client.get("/packets/recent", params={
                "node_id": node, "after_cursor": state["cursor"],
                "session_id": state["session_id"], "limit": 2000})
            response.raise_for_status()
            payload = response.json()
            if payload["reset"] or payload["gap"]:
                state = fresh(payload["session_id"])
                state["notice"] = "Session changed or buffer overrun. Recalibrate before detection."
                st.session_state.live = state
            for row in payload["packets"]:
                packet = row["packet"]
                try:
                    amplitude = packet_amplitude(packet, exclude_zeros=exclude_zeros)
                    device = packet["ts_device_us"] / 1e6
                    if state["last_device"] is not None and device < state["last_device"] - state["detector"].window_seconds:
                        state["detector"] = MotionDetector()
                        state["history"].clear()
                        state["origin"] = None
                        state["last_device"] = None
                        state["notice"] = "Device clock reset/out-of-order timestamp. Calibration reset."
                    state["last_device"] = max(device, state["last_device"]) if state["last_device"] is not None else device
                    state["detector"].update(device, amplitude, row["cursor"])
                    if state["origin"] is None:
                        state["origin"] = device
                    state["history"].append((device - state["origin"], amplitude))
                    state["processed"] += 1
                    state["latest"] = amplitude
                    state["last_seen"] = time.monotonic()
                except (ValueError, KeyError, TypeError):
                    state["invalid"] += 1
            state["cursor"] = payload["next_cursor"]
            result = state["detector"].result()
            stale = state["last_seen"] is None or time.monotonic() - state["last_seen"] > 3
            status = "NO DATA" if stale else result["status"]
            with right:
                {"MOVING": st.error, "STILL": st.success,
                 "CALIBRATING": st.info}.get(status, st.warning)(f"### {status}")
                if state["detector"].calibration:
                    st.progress(result["progress"], text="Collecting known empty-room baseline")
            cols = st.columns(5)
            cols[0].metric("Processed packets", state["processed"])
            cols[1].metric("Mean amplitude", "—" if state["latest"] is None else f'{state["latest"]:.3f}')
            cols[2].metric("Rolling variance", f'{result["variance"]:.5f}')
            cols[3].metric("Threshold", "—" if result["threshold"] is None else f'{result["threshold"]:.5f}')
            cols[4].metric("Baseline p95 variance", "—" if result["baseline"] is None else f'{result["baseline"]:.5f}')
            history = state["history"]
            if history:
                newest = history[-1][0]
                while history and history[0][0] < newest - visible:
                    history.popleft()
                frame = pd.DataFrame(history, columns=["Relative time (s)", "Mean CSI amplitude"])
                st.line_chart(frame, x="Relative time (s)", y="Mean CSI amplitude")
            if state["notice"]:
                st.caption(state["notice"])
            if state["invalid"]:
                st.warning(f'{state["invalid"]} invalid measurements skipped.')
            if payload["has_more"]:
                st.caption("Catching up with buffered packets…")
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        st.error(f"Backend unavailable or incompatible: {exc}. Check the URL and backend process.")


monitor()
