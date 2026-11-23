"""Durable educational message broker: SQLite-backed leased, acknowledged queue.

NOT production middleware. Replace with RabbitMQ quorum queues / real credentials.
"""
import os
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from common.core import open_db, log

DB_PATH = os.getenv("DB_PATH", "/data/broker.db")
@asynccontextmanager
async def lifespan(app):
    init_db()
    log("broker", "started")
    yield

app = FastAPI(title="MaltaShop demonstration broker", version="0.1", lifespan=lifespan)

class Event(BaseModel):
    event_id: str
    event_type: str
    correlation_id: str
    payload: dict

class Receipt(BaseModel):
    receipt: str


def init_db():
    with open_db(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS messages (
            event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
            correlation_id TEXT NOT NULL, payload TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending', receipt TEXT,
            lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0)""")

@app.get("/healthz")
def health():
    return {"status": "ok"}

@app.post("/events", status_code=202)
def publish(event: Event):
    import json
    with open_db(DB_PATH) as db:
        db.execute("INSERT OR IGNORE INTO messages(event_id,event_type,correlation_id,payload) VALUES(?,?,?,?)",
                   (event.event_id, event.event_type, event.correlation_id, json.dumps(event.payload)))
    log("broker", "event_accepted", event.correlation_id, event_id=event.event_id, event_type=event.event_type)
    return {"accepted": True, "event_id": event.event_id}

@app.post("/messages/claim")
def claim():
    import json
    now = datetime.now(timezone.utc).isoformat()
    lease = (datetime.now(timezone.utc) + timedelta(seconds=15)).isoformat()
    with open_db(DB_PATH) as db:
        db.execute("BEGIN IMMEDIATE")
        msg = db.execute("""SELECT * FROM messages WHERE state != 'acked'
            AND (state='pending' OR lease_until < ?) ORDER BY rowid LIMIT 1""", (now,)).fetchone()
        if msg is None:
            db.commit()
            return Response(status_code=204)
        receipt = str(uuid4())
        db.execute("UPDATE messages SET state='leased',receipt=?,lease_until=?,attempts=attempts+1 WHERE event_id=?",
                   (receipt, lease, msg["event_id"]))
        db.commit()
    return {"event_id": msg["event_id"], "event_type": msg["event_type"],
            "correlation_id": msg["correlation_id"], "payload": json.loads(msg["payload"]), "receipt": receipt}

@app.post("/messages/{event_id}/ack")
def ack(event_id: str, body: Receipt):
    with open_db(DB_PATH) as db:
        cur = db.execute("UPDATE messages SET state='acked',receipt=NULL,lease_until=NULL WHERE event_id=? AND receipt=? AND state='leased'",
                         (event_id, body.receipt))
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="lease expired or receipt mismatched")
    return {"acknowledged": True}

@app.get("/status")
def status():
    with open_db(DB_PATH) as db:
        records = db.execute("SELECT state,COUNT(*) n FROM messages GROUP BY state").fetchall()
    return {"states": {r["state"]: r["n"] for r in records}}
