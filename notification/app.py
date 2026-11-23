"""Independent notification consumer: local inbox deduplicates at-least-once events."""
import os
import threading
import json
from contextlib import asynccontextmanager
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from fastapi import FastAPI, HTTPException
from common.core import open_db, log

DB_PATH = os.getenv("DB_PATH", "/data/notification.db")
BROKER_URL = os.getenv("BROKER_URL", "http://broker:8000")
STOP = threading.Event()


def init_db():
    with open_db(DB_PATH) as db:
        db.executescript("""CREATE TABLE IF NOT EXISTS inbox (
            event_id TEXT PRIMARY KEY, processed_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS notifications (
            order_id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL,
            status TEXT NOT NULL);""")


def request_json(path: str, data: dict):
    request = Request(BROKER_URL + path, json.dumps(data).encode(),
                      {"Content-Type":"application/json"}, method="POST")
    with urlopen(request, timeout=1.5) as resp:
        if resp.status == 204:
            return None
        return json.loads(resp.read())


def consume_once():
    event = request_json("/messages/claim", {})
    if not event:
        return False
    if event["event_type"] == "OrderPlaced":
        with open_db(DB_PATH) as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("INSERT OR IGNORE INTO inbox(event_id) VALUES(?)", (event["event_id"],))
            if cursor.rowcount == 1:
                db.execute("INSERT OR IGNORE INTO notifications VALUES(?,?,?)",
                           (event["payload"]["order_id"], event["correlation_id"], "QUEUED"))
            db.commit()
        log("notification", "event_consumed", event["correlation_id"],
            order_id=event["payload"]["order_id"],event_id=event["event_id"],
            duplicate=(cursor.rowcount == 0))
    request_json(f"/messages/{event['event_id']}/ack", {"receipt": event["receipt"]})
    return True


def worker():
    while not STOP.is_set():
        try:
            more = consume_once()
        except Exception as ex:
            log("notification", "consumer_retry", error_type=type(ex).__name__)
            more = False
        if not more:
            STOP.wait(0.35)

@asynccontextmanager
async def lifespan(app):
    STOP.clear()
    init_db()
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    log("notification", "started")
    yield
    STOP.set()
    thread.join(timeout=2)

app = FastAPI(title="MaltaShop Notification", lifespan=lifespan)

@app.get("/healthz")
def health():
    return {"status": "ok"}

@app.get("/notifications/{order_id}")
def get_notification(order_id: str):
    with open_db(DB_PATH) as db:
        row = db.execute("SELECT * FROM notifications WHERE order_id=?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(404, "notification not found")
    return dict(row)
