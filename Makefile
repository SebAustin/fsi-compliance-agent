.PHONY: help install index calibrate review eval eval-smoke serve test lint type ci clean

PY := uv run

help:
	@echo "fsi-compliance-agent — make targets"
	@echo "  install     uv sync (all extras)"
	@echo "  index       build the rulebook vector index (Qdrant + voyage-3-large)"
	@echo "  calibrate   fit the abstention threshold (alpha=0.05) on labeled cases"
	@echo "  review      run a single case: make review CASE=\"...\""
	@echo "  eval        full eval on the 80 labeled cases"
	@echo "  eval-smoke  eval on a 15-case smoke subset"
	@echo "  serve       run the FastAPI server"
	@echo "  test        pytest with coverage (mocked, no network)"
	@echo "  lint        ruff check + format check"
	@echo "  type        mypy --strict on src/"
	@echo "  ci          lint + type + test"

install:
	uv sync --all-extras

index:
	$(PY) python -m scripts.build_index

calibrate:
	$(PY) python -m scripts.calibrate

review:
	$(PY) python -m scripts.review --case "$(CASE)"

eval:
	$(PY) python -m evals.run_eval --limit 80

eval-smoke:
	$(PY) python -m evals.run_eval --limit 15

serve:
	$(PY) uvicorn compliance_agent.api.server:app --reload --port 8000

test:
	$(PY) pytest

lint:
	$(PY) ruff check . && $(PY) ruff format --check .

type:
	$(PY) mypy --strict src/

ci: lint type test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
