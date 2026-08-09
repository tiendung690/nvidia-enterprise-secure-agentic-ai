.PHONY: install test compile static lint typecheck quality ingest run docker-build docker-up docker-down smoke evaluate performance retention outbox-once

install:
	python -m pip install -e ".[dev]"

test:
	pytest -m "not live"

compile:
	python -m compileall -q src scripts tests

static:
	python scripts/static_quality.py

lint:
	ruff check src scripts tests

typecheck:
	mypy src/nvidia_agentic_rag/agents src/nvidia_agentic_rag/identity \
	  src/nvidia_agentic_rag/policy src/nvidia_agentic_rag/context \
	  src/nvidia_agentic_rag/security src/nvidia_agentic_rag/data \
	  src/nvidia_agentic_rag/audit src/nvidia_agentic_rag/grounding \
	  src/nvidia_agentic_rag/query src/nvidia_agentic_rag/retrieval \
	  src/nvidia_agentic_rag/memory src/nvidia_agentic_rag/tracing \
	  src/nvidia_agentic_rag/conversation src/nvidia_agentic_rag/rag/provenance.py \
	  src/nvidia_agentic_rag/schemas.py

quality: compile static
	python scripts/validate_repo.py
	python scripts/audit_corpus.py
	pytest -m "not live"

ingest:
	agentic-rag ingest --recreate

run:
	uvicorn nvidia_agentic_rag.api:app --host 0.0.0.0 --port 8000 --reload

docker-build:
	docker compose build

docker-up:
	docker compose up -d app

docker-down:
	docker compose down

smoke:
	python scripts/docker_host_smoke.py

evaluate:
	python scripts/evaluate_api.py --base-url http://localhost:8000

performance:
	python scripts/performance_suite.py --base-url http://localhost:$${APP_PORT:-8000} --concurrency 2

retention:
	python scripts/retention_job.py --dry-run

outbox-once:
	python scripts/outbox_dispatcher.py --once
