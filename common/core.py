"""Shared, non-business helpers: logs, SQLite and input validation."""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SKU_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,39}$")


def open_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=10000")
    return con


def log(service: str, event: str, correlation_id: str = "", **fields):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": "INFO",
        "service": service,
        "event": event,
        "correlation_id": correlation_id,
    }
    record.update(fields)
    print(json.dumps(record, separators=(",", ":"), default=str), flush=True, file=sys.stdout)


def correlation(candidate: str | None) -> str:
    if not candidate or not (1 <= len(candidate) <= 80) or not re.fullmatch(r"[a-zA-Z0-9_.:-]+", candidate):
        return str(uuid4())
    return candidate


def validate_items(items: list[dict]) -> list[dict]:
    if not 1 <= len(items) <= 20:
        raise ValueError("1-20 items required")
    output = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each item must be an object")
        sku, qty = item.get("sku"), item.get("quantity")
        if not isinstance(sku, str) or not SKU_RE.fullmatch(sku):
            raise ValueError("sku must be 2-40 alphanumeric/_/- characters")
        if not isinstance(qty, int) or isinstance(qty, bool) or not 1 <= qty <= 20:
            raise ValueError("quantity must be an integer from 1 to 20")
        output.append({"sku": sku, "quantity": qty})
    return output
