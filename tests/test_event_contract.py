"""Order-to-Notification contract: actual producer outbox and consumer processing."""
import json

from fastapi.testclient import TestClient
from order import app as order_module
from notification import app as notification_module


def test_orderplaced_event_contract_is_accepted_by_notification(tmp_path, monkeypatch):
    """Verify a produced OrderPlaced event has the schema consumed downstream."""
    monkeypatch.setattr(order_module, "DB_PATH", str(tmp_path / "orders.db"))
    monkeypatch.setattr(order_module, "BROKER_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(notification_module, "DB_PATH", str(tmp_path / "notifications.db"))
    notification_module.init_db()
    with TestClient(order_module.app) as client:
        response = client.post(
            "/orders",
            json={"customer_ref": "anon-contract-17", "items": [{"sku": "LAMP-1", "quantity": 2}]},
            headers={"Idempotency-Key": "contract-basket-17", "X-Correlation-ID": "contract-cid-17"},
        )
        assert response.status_code == 202
        order_id = response.json()["order_id"]
        with order_module.open_db(order_module.DB_PATH) as db:
            row = db.execute("SELECT * FROM outbox WHERE event_type='OrderPlaced'").fetchone()
            assert row is not None
            envelope = {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "correlation_id": row["correlation_id"],
                "payload": json.loads(row["payload"]),
                "receipt": "test-lease-receipt",
            }
    assert envelope["event_type"] == "OrderPlaced"
    assert envelope["correlation_id"] == "contract-cid-17"
    assert envelope["payload"]["order_id"] == order_id
    assert envelope["payload"]["items"] == [{"sku": "LAMP-1", "quantity": 2}]

    acknowledgements = []

    def fake_broker_request(path, data):
        if path == "/messages/claim":
            return envelope
        acknowledgements.append((path, data))
        return {"acknowledged": True}

    monkeypatch.setattr(notification_module, "request_json", fake_broker_request)
    assert notification_module.consume_once() is True
    with notification_module.open_db(notification_module.DB_PATH) as db:
        row = db.execute("SELECT * FROM notifications WHERE order_id=?", (order_id,)).fetchone()
        assert row["status"] == "QUEUED"
        assert row["correlation_id"] == "contract-cid-17"
    assert acknowledgements == [(f"/messages/{envelope['event_id']}/ack", {"receipt": "test-lease-receipt"})]
