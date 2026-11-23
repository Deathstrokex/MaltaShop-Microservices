from fastapi.testclient import TestClient
from common.core import validate_items
from order import app as order_module


def test_validation_rejects_boolean_quantity():
    try:
        validate_items([{"sku": "TV-02", "quantity": True}])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_order_created_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(order_module, "DB_PATH", str(tmp_path / "orders.db"))
    monkeypatch.setattr(order_module, "BROKER_URL", "http://127.0.0.1:9")
    with TestClient(order_module.app) as client:
        headers = {"Idempotency-Key": "basket-2026-001", "X-Correlation-ID": "test-correlation-001"}
        body = {"customer_ref": "anon-51", "items": [{"sku": "TV-02", "quantity": 1}]}
        first = client.post("/orders", json=body, headers=headers)
        assert first.status_code == 202
        data = first.json()
        assert data["status"] == "ACCEPTED"
        assert data["correlation_id"] == "test-correlation-001"
        replay = client.post("/orders", json=body, headers=headers)
        assert replay.status_code == 202
        assert replay.json()["order_id"] == data["order_id"]
        assert replay.json()["replayed"] is True
        invalid = client.post("/orders", headers=headers,
                              json={"customer_ref": "anon-51", "items": [{"sku": "TV-02", "quantity": 2}]})
        assert invalid.status_code == 409
        with order_module.open_db(order_module.DB_PATH) as db:
            assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1


def test_missing_idempotency_header_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(order_module, "DB_PATH", str(tmp_path / "orders2.db"))
    monkeypatch.setattr(order_module, "BROKER_URL", "http://127.0.0.1:9")
    with TestClient(order_module.app) as client:
        res = client.post("/orders", json={"customer_ref":"anon","items":[{"sku":"ABC","quantity":1}]})
        assert res.status_code == 422
