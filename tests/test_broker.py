from fastapi.testclient import TestClient
from broker import app as broker_module


def test_message_delivery_ack_and_publish_dedup(tmp_path, monkeypatch):
    monkeypatch.setattr(broker_module, "DB_PATH", str(tmp_path / "broker.db"))
    with TestClient(broker_module.app) as client:
        event = {"event_id":"ev-123", "event_type":"OrderPlaced", "correlation_id":"cid-123",
                 "payload":{"order_id":"order-123"}}
        assert client.post("/events", json=event).status_code == 202
        assert client.post("/events", json=event).status_code == 202
        claim = client.post("/messages/claim").json()
        assert claim["event_id"] == "ev-123"
        assert client.post("/messages/ev-123/ack", json={"receipt":"bad"}).status_code == 409
        assert client.post("/messages/ev-123/ack", json={"receipt":claim["receipt"]}).status_code == 200
        assert client.post("/messages/claim").status_code == 204
        assert client.get("/status").json()["states"] == {"acked": 1}
