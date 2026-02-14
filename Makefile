.DEFAULT_GOAL := help

UV ?= uv

RUFF := $(UV) run ruff
PYRIGHT := $(UV) run pyright
IMPORT_LINT := $(UV) run lint-imports
PYTEST := $(UV) run pytest

.PHONY: help lint ruff-check format format-check typecheck imports test test-network

help:
	@printf "%s\n" \
		"Targets:" \
		"  make lint         Run ruff + pyright + import-linter" \
		"  make format       Auto-fix with ruff check --fix + ruff format" \
		"  make test         Run tests (pytest)"

lint: ruff-check typecheck imports

ruff-check:
	$(RUFF) check .

format:
	$(RUFF) check --fix .
	$(RUFF) format .

format-check:
	$(RUFF) format --check .

typecheck:
	$(PYRIGHT)

imports:
	$(IMPORT_LINT)

test:
	$(PYTEST) -m "not network"

test-network:
	$(PYTEST) -m "network"