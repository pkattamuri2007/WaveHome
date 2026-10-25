import csv

import pytest
from fastapi.testclient import TestClient

from app import main
from app.storage import Store


def make_packet(**overrides):
    pkt = {
        "schema_version": "0.1",
        "node_id": "rx1",
        "seq": 0,
        "ts_device_us": 1729280000123456,
        "rssi": -45,
        "channel": 6,
        "bandwidth_mhz": 20,
        "csi_len": 4,
        "csi": [12, -7, 3, 9],
    }
    pkt.update(overrides)
    return pkt


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", Store(data_dir=tmp_path, session="test"))
    return TestClient(main.app)


def test_valid_packet_is_stored(client, tmp_path):
    r = client.post("/ingest", json=make_packet())
    assert r.status_code == 200
    rows = list(csv.DictReader((tmp_path / "test" / "rx1.csv").open()))
    assert len(rows) == 1
    assert rows[0]["csi"] == "12 -7 3 9"


@pytest.mark.parametrize("bad", [
    {"csi_len": 5},                       # length mismatch
    {"csi": [12, -7, 3, 200]},            # out of range
    {"rssi": 10},                         # positive rssi
    {"bandwidth_mhz": 80},
    {"seq": "5"},                         # string instead of int
    {"seq": 5.0},                         # float instead of int
    {"schema_version": "0.2"},
    {"node_id": ""},
])
def test_invalid_packets_rejected(client, bad):
    assert client.post("/ingest", json=make_packet(**bad)).status_code == 422


def test_missing_field_rejected(client):
    pkt = make_packet()
    del pkt["csi"]
    assert client.post("/ingest", json=pkt).status_code == 422


def test_batch_and_drop_tracking(client):
    batch = [make_packet(seq=s) for s in (0, 1, 2, 5, 6)] + [make_packet(node_id="rx2", seq=0)]
    r = client.post("/ingest/batch", json=batch)
    assert r.json() == {"accepted": 6}
    nodes = client.get("/nodes").json()
    assert nodes["rx1"]["packets"] == 5
    assert nodes["rx1"]["dropped"] == 2
    assert nodes["rx2"]["packets"] == 1


def test_bad_packet_rejects_whole_batch(client):
    batch = [make_packet(seq=0), make_packet(seq=1, csi_len=99)]
    assert client.post("/ingest/batch", json=batch).status_code == 422
    assert client.get("/nodes").json() == {}


def test_node_id_cannot_escape_data_dir(client, tmp_path):
    client.post("/ingest", json=make_packet(node_id="../../evil"))
    assert not (tmp_path.parent / "evil.csv").exists()
    assert len(list((tmp_path / "test").glob("*.csv"))) == 1
