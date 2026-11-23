# MaltaShop — Place an Order (educational microservices prototype)

A runnable MQF Level 5 SOA & Microservices Fundamentals case study prototype. It contains an independent **Order** REST API, a durable **educational broker**, and an independent **Notification** consumer. **Order, Notification, and Broker each own a different SQLite database.** The Order transaction creates the Order record plus an outbox event atomically; a relay publishes an `OrderPlaced` message. Notification records receipt in its own inbox before acknowledging. Structured JSON logs carry the same correlation ID.

Payment and Inventory are proposed saga participants **not implemented** in this prototype. Nothing here processes cards or real personal data.

## Start with Docker

Install Docker Desktop with Compose, then in the repository root:

```bash
docker compose up --build -d --wait
curl -i http://localhost:8000/healthz
curl -i -X POST http://localhost:8000/orders \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: basket-001' \
  -H 'X-Correlation-ID: demo-001' \
  -d '{"customer_ref":"demo-customer","items":[{"sku":"TV-02","quantity":1}]}'
docker compose logs --no-color order notification broker
docker compose down -v
```

The order endpoint replies **202 Accepted**. To follow the correlation ID `demo-001`, look for `order_accepted`, `event_published` and `event_consumed` in the container logs. `GET /orders/{order_id}` retrieves the order.

## Environment variables and data

| Variable | Service | Default in Compose | Meaning |
|---|---|---|---|
| `DB_PATH` | Order | `/data/order.db` | Private Order and outbox storage |
| `DB_PATH` | Notification | `/data/notification.db` | Private Notification and inbox storage |
| `DB_PATH` | Broker | `/data/broker.db` | Durable local message queue |
| `BROKER_URL` | Order, Notification | `http://broker:8000` | Internal broker endpoint |

Three distinct Docker named volumes persist demonstration state. Only port 8000 on the Order service is exposed. No secrets are committed.

## Test and CI

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -v
python scripts/verify_local_end_to_end.py
```

The GitHub Actions workflow at [`.github/workflows/ci.yml`](.github/workflows/ci.yml) validates syntax, six automated tests, local cross-service event delivery, Docker Compose configuration/build, the Order API smoke test, the Notification inbox and broker acknowledgement. A passing Actions run is a separate **hosted** check; local logs are not a substitute.

## Design and limitations

```
Client -> Order REST -> private order.db (Orders + Outbox)
                              |
                              v
                   durable educational broker.db
                              |
                              v
                     Notification consumer
                              |
                              v
                     private notification.db (Inbox)
```

- `Idempotency-Key` deduplicates repeated order requests; an incompatible replay gets HTTP 409.
- Broker event IDs deduplicate publishing and its 15-second lease allows redelivery after a crash.
- Notification inbox `event_id` ensures repeat-safe processing; correlation IDs appear in both services.
- This is a minimal educational SQLite-backed queue, **not RabbitMQ**, not pub-sub fan-out and not production HA. Replace it with a hardened broker and managed databases before production.
- Missing by design: Payment/Inventory saga implementation, real email/SMS, auth, GDPR processing, horizontal scaling, security hardening, dead-letter handling, tracing and encryption.

Refer to the technical assignment for the proposed production architecture, operational controls and future implementation. Original architecture diagrams are in `diagrams/`. Evidence must be attributed to the environment in which it was produced.
