from test_ingest import client, make_packet
from app import main
from app.storage import Store


def test_cursor_order_filter_and_repeat(client):
    packets = [make_packet(seq=9), make_packet(node_id="rx2"),
               make_packet(seq=1), make_packet(seq=1)]
    client.post("/ingest/batch", json=packets)
    first = client.get("/packets/recent", params={"node_id": "rx1", "limit": 2}).json()
    assert [x["packet"]["seq"] for x in first["packets"]] == [9, 1]
    assert first["has_more"]
    second = client.get("/packets/recent", params={
        "node_id": "rx1", "after_cursor": first["next_cursor"]}).json()
    assert len(second["packets"]) == 1
    assert second["packets"][0]["cursor"] > first["next_cursor"]
    assert not client.get("/packets/recent", params={"after_cursor": second["next_cursor"]}).json()["packets"]


def test_bound_and_same_name_session_reset(client, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", Store(tmp_path, session="test", recent_capacity=2))
    client.post("/ingest/batch", json=[make_packet(seq=i) for i in range(4)])
    old = client.get("/packets/recent", params={"after_cursor": 1}).json()
    assert old["gap"] and len(old["packets"]) == 2
    client.post("/session", json={"name": "test"})
    client.post("/ingest", json=make_packet(seq=0))
    new = client.get("/packets/recent", params={
        "after_cursor": old["next_cursor"], "session_id": old["session_id"]}).json()
    assert new["reset"] and len(new["packets"]) == 1
    assert new["session_id"] != old["session_id"]


def test_invalid_queries(client):
    for query in ("limit=0", "limit=2001", "after_cursor=-1", "after_cursor=x", "node_id="):
        assert client.get("/packets/recent?" + query).status_code == 422


def test_concurrent_writers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from app.schema import CSIPacket
    store = Store(tmp_path, recent_capacity=50)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: store.add([CSIPacket(**make_packet(seq=i))]), range(80)))
    result = store.recent(limit=100)
    assert len(result["packets"]) == 50
    assert [r["cursor"] for r in result["packets"]] == list(range(31, 81))
    assert store.node_snapshot()["rx1"]["packets"] == 80


def test_future_cursor_rejected(client):
    assert client.get("/packets/recent?after_cursor=999").status_code == 409
