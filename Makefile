PY ?= .venv/bin/python

.PHONY: venv install test lint typecheck demo run scan check

venv:
	python3 -m venv .venv
	$(PY) -m pip install --upgrade pip

install: venv
	$(PY) -m pip install -e '.[dev,discord]'

test:
	$(PY) -m pytest --cov=human_approved_agents --cov-report=term-missing

lint:
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

typecheck:
	$(PY) -m mypy

demo:
	$(PY) -m human_approved_agents.demo

run:
	$(PY) -m human_approved_agents run --adapter cli

scan:
	sh scripts/check-secrets.sh

check: lint typecheck test demo scan
