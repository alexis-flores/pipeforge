PY := .venv/bin/python
COV ?= 60

.PHONY: verify lint type test

verify: lint type test

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

type:
	.venv/bin/mypy src/pipeforge/core

test:
	QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q --cov=src/pipeforge --cov-fail-under=$(COV)
