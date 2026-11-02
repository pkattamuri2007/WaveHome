import json
import random
import socket
import time

import pytest
from fastapi.testclient import TestClient

import fake_sender
from app.main import create_app
from app.storage import load_session


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
def app(tmp_path):
    return create_app(data_dir=tmp_path, udp_port=None)


@pytest.fixture
def client(app):
    return TestClient(app)


def stats(client):
    return client.get("/stats").json()


def test_valid_packet_is_stored(client, app):
    r = client.post("/ingest", json=make_packet())
    assert r.status_code == 200
    rows = load_session(app.state.ingestor.session_dir)["rx1"]
    assert len(rows) == 1
    assert rows[0]["csi"] == [12, -7, 3, 9]


@pytest.mark.parametrize("bad", [
    {"csi_len": 5},                       # length mismatch
    {"csi": [12, -7, 3, 200]},            # out of range
    {"rssi": 10},                         # positive rssi
    {"bandwidth_mhz": 80},
    {"seq": "5"},                         # string instead of int
    {"seq": 5.0},                         # float instead of int
    {"seq": True},                        # bool instead of int
    {"schema_version": "0.2"},
    {"node_id": ""},
])
def test_invalid_packets_rejected_and_counted(client, bad):
    r = client.post("/ingest", json=make_packet(**bad))
    assert r.status_code == 422
    assert r.json()["reason"]
    s = stats(client)
    assert s["totals"]["rejected"] == 1
    assert s["totals"]["accepted"] == 0


def test_missing_field_rejected(client):
    pkt = make_packet()
    del pkt["csi"]
    r = client.post("/ingest", json=pkt)
    assert r.status_code == 422
    assert "csi" in r.json()["reason"]
    assert stats(client)["nodes"]["rx1"]["rejected"] == 1


def test_unattributable_rejection_counts_as_unknown(client):
    assert client.post("/ingest", content=b'{"node_id": "rx1", "se').status_code == 422
    assert client.post("/ingest", json=make_packet(node_id=7)).status_code == 422
    s = stats(client)
    assert s["nodes"]["unknown"]["rejected"] == 2
    assert [x["reason"] for x in s["recent_rejections"]][0] == "invalid JSON"


def test_batch_validates_each_packet(client):
    batch = [make_packet(seq=s) for s in (0, 1, 2, 5, 6)] + [make_packet(node_id="rx2", seq=0)]
    batch.insert(2, make_packet(seq=99, csi_len=99))
    r = client.post("/ingest/batch", json=batch)
    assert r.json()["accepted"] == 6
    assert r.json()["rejected"] == 1
    assert r.json()["errors"][0]["index"] == 2
    nodes = stats(client)["nodes"]
    assert nodes["rx1"]["accepted"] == 5
    assert nodes["rx1"]["dropped"] == 2
    assert nodes["rx1"]["rejected"] == 1
    assert nodes["rx2"]["accepted"] == 1


def test_batch_must_be_array(client):
    assert client.post("/ingest/batch", json=make_packet()).status_code == 422


def test_rate_reported(client):
    for s in range(20):
        client.post("/ingest", json=make_packet(seq=s))
    assert stats(client)["nodes"]["rx1"]["rate_hz"] > 0


def test_new_session_resets_stats(client, app):
    client.post("/ingest", json=make_packet())
    assert client.post("/session", json={"name": "walk-zone-a"}).json() == {"session": "walk-zone-a"}
    assert stats(client)["nodes"] == {}
    client.post("/ingest", json=make_packet())
    assert app.state.ingestor.session_dir.name == "walk-zone-a"
    assert len(load_session(app.state.ingestor.session_dir)["rx1"]) == 1


def test_node_id_cannot_escape_data_dir(client, tmp_path):
    client.post("/ingest", json=make_packet(node_id="../../evil"))
    assert not (tmp_path.parent / "evil.csv").exists()
    assert len(list(tmp_path.glob("*/*.csv"))) == 1


def test_udp_ingest(tmp_path):
    app = create_app(data_dir=tmp_path, udp_port=0, udp_host="127.0.0.1")
    with TestClient(app) as client:
        port = app.state.udp_port
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for seq in (0, 1, 3):
                s.sendto(json.dumps(make_packet(seq=seq)).encode(), ("127.0.0.1", port))
            s.sendto(b"garbage", ("127.0.0.1", port))
        for _ in range(50):
            st = stats(client)
            if st["totals"]["accepted"] + st["totals"]["rejected"] == 4:
                break
            time.sleep(0.05)
        assert st["nodes"]["rx1"]["accepted"] == 3
        assert st["nodes"]["rx1"]["dropped"] == 1
        assert st["nodes"]["unknown"]["rejected"] == 1
        assert st["recent_rejections"][0]["transport"] == "udp"


@pytest.mark.parametrize("kind", fake_sender.BAD_KINDS)
def test_generator_bad_packets_are_all_rejected(app, kind):
    ingestor = app.state.ingestor
    rng = random.Random(0)
    node = fake_sender.FakeNode("rx1", rng)
    for _ in range(200):
        bad = fake_sender.make_bad(node.packet(time.time(), False, 6), kind, rng)
        raw = bad if isinstance(bad, bytes) else json.dumps(bad).encode()
        assert ingestor.handle_raw(raw, "test") is not None, bad
    rejected = ingestor.snapshot()["nodes"]
    assert sum(n["rejected"] for n in rejected.values()) == 200


def test_generator_valid_packets_round_trip(app):
    ingestor = app.state.ingestor
    node = fake_sender.FakeNode("rx1", random.Random(0))
    sent = [node.packet(time.time(), moving, 6) for moving in [False, True] * 50]
    for p in sent:
        assert ingestor.handle_raw(json.dumps(p).encode(), "test") is None
    ingestor.close()
    loaded = load_session(ingestor.session_dir)["rx1"]
    fields = [k for k in sent[0] if k != "schema_version"]  # schema_version isn't stored
    assert [{k: p[k] for k in fields} for p in loaded] == [{k: p[k] for k in fields} for p in sent]
