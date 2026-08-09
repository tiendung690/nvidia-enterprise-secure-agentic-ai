# Message Queue Hands-on Lab V1

This lab connects the two repositories without turning RabbitMQ into a toy side project.

```text
DCEA order source
    -> enterprise.events (RabbitMQ topic exchange)
    -> dcea.orders.ingest
    -> manual ACK consumer
    -> SQLite inbox + landing (same local transaction)
    -> Bronze -> Silver -> Gold Delta
    -> lakehouse.gold.published.v1
    -> agent.lakehouse.events

Agentic AI Postgres transaction
    -> agent_outbox
    -> outbox dispatcher
    -> enterprise.events
    -> agent.memory.events
    -> Postgres inbox
```

The local lab intentionally uses RabbitMQ because it makes routing, ACK, redelivery,
retry queues and DLQ behavior visible. The AWS phase can keep the event contracts and
consumer idempotency while replacing the transport with EventBridge/SQS.

## 0. Prerequisites

- Docker Desktop + WSL2
- the two repos must be sibling folders, e.g.
  - `/mnt/d/Databriks/dcea_demo`
  - `/mnt/d/Databriks/nvidia-enterprise-secure-agentic-ai`
- Do not commit `.env`, `.env.bak`, NVIDIA keys or other credentials.

## 1. Validate Compose overlays

Agentic:

```bash
cd /mnt/d/Databriks/nvidia-enterprise-secure-agentic-ai
docker compose -f docker-compose.yml -f docker-compose.messaging.yml config >/tmp/agentic-compose.txt
```

DCEA:

```bash
cd /mnt/d/Databriks/dcea_demo
docker compose -f docker-compose.yml -f docker-compose.messaging.yml config >/tmp/dcea-compose.txt
```

## 2. Build Agentic messaging image and start broker/database

```bash
cd /mnt/d/Databriks/nvidia-enterprise-secure-agentic-ai

docker compose -f docker-compose.yml -f docker-compose.messaging.yml build \
  memory-event-consumer lakehouse-event-consumer outbox-dispatcher

docker compose -f docker-compose.yml -f docker-compose.messaging.yml up -d \
  postgres rabbitmq
```

RabbitMQ UI:

- URL: `http://localhost:15672`
- user: `lab`
- password: `labpass`

Apply the new SQL migration even if `postgres_data` already existed before this lab:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml exec -T postgres \
  psql -U agentic_admin -d agentic_ai < ops/sql/006_messaging_lab.sql
```

Verify:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml exec -T postgres \
  psql -U agentic_admin -d agentic_ai \
  -c "select to_regclass('public.agent_message_inbox'), to_regclass('public.agent_dlq_record');"
```

Start the consumers first so they own/declare their queue topology before any producer drains existing outbox rows:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml up -d \
  memory-event-consumer lakehouse-event-consumer

docker compose -f docker-compose.yml -f docker-compose.messaging.yml logs --tail=50 \
  memory-event-consumer lakehouse-event-consumer
```

After both consumers print `status=ready`, start the outbox dispatcher:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml up -d \
  outbox-dispatcher
```

Follow logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml logs -f \
  memory-event-consumer lakehouse-event-consumer outbox-dispatcher
```

## 3. Build DCEA and prepare source data

```bash
cd /mnt/d/Databriks/dcea_demo

docker compose -f docker-compose.yml -f docker-compose.messaging.yml build

docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  dcea-associate python -m dcea_associate_demo reset

docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  dcea-associate python -m dcea_associate_demo seed
```

Start the order consumer:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml up -d \
  order-event-consumer
```

Watch it:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml logs -f \
  order-event-consumer
```

## 4. Lab A - topic routing + duplicate suppression

Publish each source order three times **with the same event_id**:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  dcea-associate python /workspace/scripts/publish_order_events.py --duplicate-each 3
```

There are 4 source orders, so 12 deliveries are published. Expected consumer result:

```text
processed             = 4
duplicate_suppressed  = 8
```

Verify the SQL inbox/landing state:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  dcea-associate python -c "import sqlite3; c=sqlite3.connect('/workspace/tmp/order-events.db'); print('inbox=', c.execute('select count(*) from message_inbox').fetchone()[0]); print('landing=', c.execute('select count(*) from order_event_landing').fetchone()[0])"
```

Expected after a clean lab:

```text
inbox=4
landing=4
```

## 5. Materialize queue-ingested orders into the DCEA data pipeline

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  dcea-associate python /workspace/scripts/materialize_order_events.py
```

Now Bronze should use the event source instead of the original Parquet source:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  -e DCEA_ORDERS_SOURCE=events \
  dcea-associate python -m dcea_associate_demo bronze

docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  dcea-associate python -m dcea_associate_demo silver

docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  dcea-associate python -m dcea_associate_demo gold

docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  dcea-associate python -m dcea_associate_demo report
```

The Gold tables remain:

```text
gold_customer_order_summary
gold_book_sales_summary
```

The important difference is that the order path is now:

```text
source Parquet -> RabbitMQ -> idempotent landing -> Bronze -> Silver -> Gold
```

## 6. Lab B - DCEA Gold event -> Agentic consumer

Publish only metadata/control information, not Gold rows:

```bash
cd /mnt/d/Databriks/dcea_demo

docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  dcea-associate python /workspace/scripts/publish_gold_event.py
```

Then verify in Agentic Postgres:

```bash
cd /mnt/d/Databriks/nvidia-enterprise-secure-agentic-ai

docker compose -f docker-compose.yml -f docker-compose.messaging.yml exec -T postgres \
  psql -U agentic_admin -d agentic_ai \
  -c "select consumer_name,event_id,event_type,status,processed_at from agent_message_inbox where consumer_name='lakehouse-refresh-consumer' order by received_at desc limit 10;"
```

Expected event type:

```text
lakehouse.gold.published.v1
```

The event contains table versions/fingerprint. The actual Gold data stays in Delta.

## 7. Lab C - transactional outbox -> RabbitMQ

The Agentic repo already writes memory lifecycle events to `agent_outbox`. For a broker-only
exercise you can insert one lab event directly:

```bash
cd /mnt/d/Databriks/nvidia-enterprise-secure-agentic-ai

docker compose -f docker-compose.yml -f docker-compose.messaging.yml exec -T postgres \
  psql -U agentic_admin -d agentic_ai -c "insert into agent_outbox(event_id,aggregate_type,aggregate_id,event_type,tenant_id,user_id,payload) values ('EVT-LAB-OUTBOX-001','memory','MEM-LAB-001','memory.promoted','tenant-a','user-a','{\"correlation_id\":\"COR-LAB-001\",\"source\":\"mq-lab\"}'::jsonb) on conflict do nothing;"
```

Verify dispatcher state:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml exec -T postgres \
  psql -U agentic_admin -d agentic_ai \
  -c "select event_id,event_type,published_at,publish_attempts from agent_outbox where event_id='EVT-LAB-OUTBOX-001';"
```

Verify consumer state:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml exec -T postgres \
  psql -U agentic_admin -d agentic_ai \
  -c "select consumer_name,event_id,event_type,status from agent_message_inbox where event_id='EVT-LAB-OUTBOX-001';"
```

For the full domain version, run the Agentic app with `MEMORY_BACKEND=postgres` and call
`POST /v1/memory/promote`; the existing repository writes `agent_memory` and `agent_outbox`
in the same PostgreSQL transaction.

## 8. Lab D - broker outage and outbox recovery

Stop RabbitMQ while keeping PostgreSQL alive:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml stop rabbitmq
```

Insert another outbox event:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml exec -T postgres \
  psql -U agentic_admin -d agentic_ai -c "insert into agent_outbox(event_id,aggregate_type,aggregate_id,event_type,tenant_id,user_id,payload) values ('EVT-LAB-OUTBOX-002','memory','MEM-LAB-002','memory.promoted','tenant-a','user-a','{}'::jsonb) on conflict do nothing;"
```

It must remain unpublished:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml exec -T postgres \
  psql -U agentic_admin -d agentic_ai \
  -c "select event_id,published_at from agent_outbox where event_id='EVT-LAB-OUTBOX-002';"
```

Start the broker again:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml start rabbitmq
```

The dispatcher is configured to restart. After RabbitMQ becomes healthy, verify that the
row gets `published_at` and the memory consumer receives it.

This is the failure mode to explain in an interview: database commit succeeds while the
broker is unavailable; the durable outbox prevents loss and the dispatcher catches up.

## 9. Lab E - crash after DB commit but before ACK

This is the most important at-least-once exercise.

Start a DCEA consumer with fault injection:

```bash
cd /mnt/d/Databriks/dcea_demo
export LAB_CRASH_AFTER_COMMIT_ORDER_ID=O003
unset LAB_TRANSIENT_FAIL_ORDER_ID
unset LAB_TRANSIENT_FAIL_COUNT

docker compose -f docker-compose.yml -f docker-compose.messaging.yml up -d \
  --force-recreate order-event-consumer
```

Publish a fresh set:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  dcea-associate python /workspace/scripts/publish_order_events.py
```

Watch logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml logs -f \
  order-event-consumer
```

For O003 the process commits the inbox/landing transaction and deliberately exits before
ACK. RabbitMQ redelivers after the consumer restarts. The second delivery sees the same
`event_id`, becomes `duplicate_suppressed`, and is ACKed without repeating the side effect.

Clear the injected fault afterwards:

```bash
unset LAB_CRASH_AFTER_COMMIT_ORDER_ID
docker compose -f docker-compose.yml -f docker-compose.messaging.yml up -d \
  --force-recreate order-event-consumer
```

## 10. Lab F - bounded transient retry

Inject two transient failures for O002:

```bash
export LAB_TRANSIENT_FAIL_ORDER_ID=O002
export LAB_TRANSIENT_FAIL_COUNT=2

docker compose -f docker-compose.yml -f docker-compose.messaging.yml up -d \
  --force-recreate order-event-consumer

docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  dcea-associate python /workspace/scripts/publish_order_events.py
```

Expected for O002:

```text
initial delivery -> enterprise.retry
5s delay          -> delivery #2 -> enterprise.retry
5s delay          -> delivery #3 -> success -> ACK
```

Clear:

```bash
unset LAB_TRANSIENT_FAIL_ORDER_ID
unset LAB_TRANSIENT_FAIL_COUNT
docker compose -f docker-compose.yml -f docker-compose.messaging.yml up -d \
  --force-recreate order-event-consumer
```

## 11. Lab G - poison message -> DLQ

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  dcea-associate python /workspace/scripts/publish_poison_message.py
```

The consumer classifies malformed JSON as permanent, records it in the local SQL failure
ledger and rejects with `requeue=false`. RabbitMQ dead-letters it to:

```text
dcea.orders.ingest.dlq
```

Verify the local failure ledger:

```bash
docker compose -f docker-compose.yml -f docker-compose.messaging.yml run --rm \
  dcea-associate python -c "import sqlite3; c=sqlite3.connect('/workspace/tmp/order-events.db'); print(c.execute('select event_id,error_class,retry_count,error_message from dlq_record order by id desc limit 5').fetchall())"
```

Also inspect the DLQ from the RabbitMQ UI.

## 12. Queue/consumer signals to observe

In RabbitMQ UI watch:

- Ready messages
- Unacked messages
- Redeliveries
- consumer count
- publish/deliver/ack rates
- `dcea.orders.ingest.retry`
- `dcea.orders.ingest.dlq`
- `agent.memory.events`
- `agent.lakehouse.events`

The next iteration should export these as Prometheus counters/gauges and alert on oldest
message age, queue depth, DLQ count and outbox backlog.

## 13. Cleanup

DCEA:

```bash
cd /mnt/d/Databriks/dcea_demo
docker compose -f docker-compose.yml -f docker-compose.messaging.yml down
```

Agentic:

```bash
cd /mnt/d/Databriks/nvidia-enterprise-secure-agentic-ai
docker compose -f docker-compose.yml -f docker-compose.messaging.yml down
```

Do **not** add `-v` unless you intentionally want to delete PostgreSQL/RabbitMQ runtime state.

## 14. Interview story after completing these labs

SSE:

> We used at-least-once delivery with manual ACK. The consumer ACKed only after a durable
> side effect, and an inbox keyed by `(consumer_name,event_id)` made redelivery safe.

TL:

> We separated producer intent from broker topology, versioned event contracts, bounded
> retries, classified permanent failures into a DLQ, controlled prefetch/backpressure and
> tested crash-after-commit-before-ACK explicitly.

TA/SA:

> We used transactional outbox for DB+event dual-write safety. RabbitMQ made delivery
> semantics observable in the local lab; for AWS the event contract and idempotent consumer
> remain stable while the transport can move to EventBridge/SQS. Gold tables remain in the
> data plane; the broker carries metadata/control events rather than large datasets.
