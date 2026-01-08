.DEFAULT_GOAL := help

UV ?= uv

RUFF := $(UV) run ruff
PYRIGHT := $(UV) run pyright
IMPORT_LINT := $(UV) run lint-imports
PYTEST := $(UV) run pytest

.PHONY: help lint lint-fix ruff-check format format-check typecheck imports test

help:
	@printf "%s\n" \
		"Targets:" \
		"  make lint         Run ruff + pyright + import-linter" \
		"  make lint-fix     Auto-fix with ruff check --fix + ruff format" \
		"  make format       Format code (ruff format)" \
		"  make test         Run tests (pytest)"

lint: ruff-check typecheck imports

ruff-check:
	$(RUFF) check .

format:
	$(RUFF) format .

format-check:
	$(RUFF) format --check .

typecheck:
	$(PYRIGHT)

imports:
	$(IMPORT_LINT)

lint-fix:
	$(RUFF) check --fix .
	$(RUFF) format .

test:
	$(PYTEST)