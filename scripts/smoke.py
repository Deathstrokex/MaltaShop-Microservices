"""Public REST smoke: checks order creation and idempotent replay."""
import json
import sys
from urllib.request import Request, urlopen
from uuid import uuid4
base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
key = "smoke-" + str(uuid4())
request = Request(base + "/orders",
                  json.dumps({"customer_ref": "synthetic-smoke", "items": [{"sku": "TV-02", "quantity": 1}]}).encode(),
                  {"Content-Type": "application/json", "Idempotency-Key": key}, method="POST")
with urlopen(request, timeout=10) as res:
    result = json.loads(res.read())
assert result["status"] == "ACCEPTED"
with urlopen(request, timeout=10) as res:
    duplicate = json.loads(res.read())
assert duplicate["order_id"] == result["order_id"] and duplicate["replayed"]
print("SMOKE PASS", json.dumps(result))
