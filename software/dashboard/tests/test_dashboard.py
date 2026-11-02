"""Exercise rendered widgets and chart data without a browser driver."""
from pathlib import Path
import httpx
from streamlit.testing.v1 import AppTest
from app import main
from app.storage import Store
from app.schema import CSIPacket
from test_ingest import make_packet


def test_dashboard_polls_without_duplicates_and_calibrates(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(main, "store", store)
    store.add([CSIPacket(**make_packet(seq=i, ts_device_us=i * 20000)) for i in range(110)])
    from fastapi.testclient import TestClient
    class LocalClient:
        def __init__(self, **kwargs):
            self.client = TestClient(main.app)
        def __enter__(self):
            return self.client
        def __exit__(self, *args):
            self.client.close()
    monkeypatch.setattr(httpx, "Client", LocalClient)
    # TestClient subclasses the original Client and is unaffected by the constructor patch.
    app = AppTest.from_file(str(Path(__file__).parents[2] / "backend/live_dashboard.py"))
    app.run(timeout=15)
    assert not app.exception
    assert app.session_state["live"]["processed"] == 110
    app.run()
    assert app.session_state["live"]["processed"] == 110
    app.button[0].click().run()
    assert app.session_state["live"]["detector"].calibration is not None
    for start in range(110, 610, 25):
        store.add([CSIPacket(**make_packet(seq=i, ts_device_us=i * 20000))
                   for i in range(start, start + 25)])
        app.run()
        assert not app.exception
    state = app.session_state["live"]
    assert state["detector"].threshold == 0.01
    assert state["detector"].status == "STILL"
    assert state["history"]

    # A restarted device must reset once, then accumulate a new window normally.
    store.add([CSIPacket(**make_packet(seq=i, ts_device_us=i * 20000))
               for i in range(150)])
    app.run()
    state = app.session_state["live"]
    assert not app.exception
    assert len(state["history"]) == 150
    assert state["last_device"] == 2.98
    assert len(state["detector"].samples) >= 90
    assert state["detector"].status == "UNCALIBRATED"
