"""Order REST API with separate SQLite ownership and transactional outbox."""
import json
import os
import threading
from contextlib import asynccontextmanager
from time import sleep
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from common.core import correlation, log, open_db, validate_items

DB_PATH = os.getenv("DB_PATH", "/data/order.db")
BROKER_URL = os.getenv("BROKER_URL", "http://broker:8000")
STOP = threading.Event()

class PlaceOrder(BaseModel):
    customer_ref: str
    items: list[dict]


def init_db():
    with open_db(DB_PATH) as db:
        db.executescript("""CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
            customer_ref TEXT NOT NULL, items TEXT NOT NULL,
            status TEXT NOT NULL, correlation_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox (
            event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
            correlation_id TEXT NOT NULL, payload TEXT NOT NULL,
            published INTEGER NOT NULL DEFAULT 0);""")


def publish_once():
    with open_db(DB_PATH) as db:
        rows = db.execute("SELECT * FROM outbox WHERE published=0 LIMIT 20").fetchall()
    for row in rows:
        envelope = {"event_id":row["event_id"],"event_type":row["event_type"],
                    "correlation_id":row["correlation_id"], "payload": json.loads(row["payload"])}
        payload = json.dumps(envelope).encode("utf-8")
        try:
            request = Request(BROKER_URL + "/events", payload, {"Content-Type":"application/json"}, method="POST")
            with urlopen(request, timeout=1.5) as response:
                if response.status != 202:
                    raise OSError("broker rejected publication")
            with open_db(DB_PATH) as db:
                db.execute("UPDATE outbox SET published=1 WHERE event_id=?", (row["event_id"],))
            log("order", "event_published", row["correlation_id"], event_id=row["event_id"])
        except Exception as ex:
            log("order", "outbox_retry", row["correlation_id"], event_id=row["event_id"], error_type=type(ex).__name__)


def relay_loop():
    while not STOP.is_set():
        publish_once()
        STOP.wait(0.3)

@asynccontextmanager
async def lifespan(app):
    STOP.clear()
    init_db()
    thread = threading.Thread(target=relay_loop, daemon=True)
    thread.start()
    log("order", "started")
    yield
    STOP.set()
    thread.join(timeout=2)

app = FastAPI(title="MaltaShop Order", lifespan=lifespan)

@app.get("/healthz")
def health():
    return {"status": "ok"}

@app.get("/readyz")
def ready():
    with open_db(DB_PATH) as db:
        db.execute("SELECT 1")
    return {"ready": True}

@app.post("/orders", status_code=202)
def place_order(order: PlaceOrder, idempotency_key: str = Header(..., min_length=6, max_length=80),
                x_correlation_id: str | None = Header(default=None)):
    if not order.customer_ref or len(order.customer_ref) > 80:
        raise HTTPException(422, "invalid customer_ref")
    try:
        items = validate_items(order.items)
    except ValueError as ex:
        raise HTTPException(422, str(ex))
    corr = correlation(x_correlation_id)
    with open_db(DB_PATH) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM orders WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if row:
            if row["customer_ref"] != order.customer_ref or row["items"] != json.dumps(items, sort_keys=True):
                db.rollback()
                raise HTTPException(409, "same idempotency key used with different order")
            db.commit()
            return {"order_id": row["order_id"], "status": row["status"],
                    "correlation_id": row["correlation_id"], "replayed": True}
        order_id = str(uuid4())
        event_id = str(uuid4())
        db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?)",
                   (order_id,idempotency_key,order.customer_ref,json.dumps(items, sort_keys=True),"ACCEPTED",corr))
        db.execute("INSERT INTO outbox VALUES(?,?,?,?,0)",
                   (event_id,"OrderPlaced",corr,json.dumps({"order_id":order_id,"items":items})))
        db.commit()
    log("order", "order_accepted", corr, order_id=order_id, event_id=event_id)
    return {"order_id": order_id, "status": "ACCEPTED", "correlation_id": corr, "replayed": False}

@app.get("/orders/{order_id}")
def get_order(order_id: str):
    with open_db(DB_PATH) as db:
        row = db.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(404, "order not found")
    return {"order_id":row["order_id"],"status":row["status"],"items":json.loads(row["items"])}
