.DEFAULT_GOAL := help

UV ?= uv
PNPM := pnpm

RUFF := $(UV) run ruff
PYRIGHT := $(UV) run pyright
IMPORT_LINT := $(UV) run lint-imports
PYTEST := $(UV) run pytest

.PHONY: help lint ruff-check format format-check typecheck imports test test-network \
        web-lint web-format web-format-check

help:
	@printf "%s\n" \
		"Targets:" \
		"  make lint         Run ruff + pyright + import-linter + web eslint" \
		"  make format       Auto-fix with ruff + prettier" \
		"  make test         Run tests (pytest)"

lint: ruff-check typecheck imports web-lint

ruff-check:
	$(RUFF) check .

format:
	$(RUFF) check --fix .
	$(RUFF) format .
	cd web && $(PNPM) format

format-check:
	$(RUFF) format --check .
	cd web && $(PNPM) format:check

typecheck:
	$(PYRIGHT)

imports:
	$(IMPORT_LINT)

web-lint:
	cd web && $(PNPM) lint

web-format:
	cd web && $(PNPM) format

web-format-check:
	cd web && $(PNPM) format:check

test:
	$(PYTEST) -m "not network"

test-network:
	$(PYTEST) -m "network"