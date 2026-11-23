# MaltaShop Microservices — educational prototype

A two-service e-commerce order demonstration for Unit 5 (SOA and Microservices Fundamentals). The prototype includes an Order HTTP API, asynchronous `OrderPlaced` delivery through a durable local broker, and an independent Notification consumer.

**Scope:** This is an educational example, not a payment system. Order and Notification own separate SQLite databases. A transactional outbox, idempotency keys, an inbox, and a shared correlation ID illustrate failure-resistant messaging. Payment and Inventory saga stages are architecture proposals only.

## Run

```bash
docker compose up --build -d --wait
curl -i http://localhost:8000/healthz
curl -i -X POST http://localhost:8000/orders -H 'Content-Type: application/json' -H 'Idempotency-Key: basket-001' -H 'X-Correlation-ID: demo-001' -d '{"customer_ref":"customer-demo","items":[{"sku":"TV-02","quantity":1}]}'
docker compose logs order notification broker
```

Run local tests with `python -m pip install -r requirements-dev.txt && python -m pytest tests -v`.

The workflow under `.github/workflows/ci.yml` checks tests and the integrated Compose flow. Do not treat local screenshots as evidence of a hosted pipeline run.