from notification import app as notification_module


def test_consumer_inbox_deduplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(notification_module, "DB_PATH", str(tmp_path / "notification.db"))
    notification_module.init_db()
    event = {"event_id":"ev-7", "event_type":"OrderPlaced", "correlation_id":"cid-7",
             "payload":{"order_id":"ord-7"}, "receipt":"demo"}
    responses = [event, event]
    acknowledgements = []

    def fake_request(path, data):
        if path == "/messages/claim":
            return responses.pop(0) if responses else None
        acknowledgements.append((path, data))
        return {"acknowledged":True}

    monkeypatch.setattr(notification_module, "request_json", fake_request)
    assert notification_module.consume_once() is True
    assert notification_module.consume_once() is True
    with notification_module.open_db(notification_module.DB_PATH) as db:
        assert db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 1
    assert len(acknowledgements) == 2
