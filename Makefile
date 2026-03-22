.DEFAULT_GOAL := help

UV ?= uv
NPM := $(if $(shell command -v pnpm 2>/dev/null),pnpm,npm)

RUFF := $(UV) run ruff
PYRIGHT := $(UV) run pyright
IMPORT_LINT := $(UV) run lint-imports
PYTEST := $(UV) run pytest

.PHONY: help install build build-web lint ruff-check format format-check typecheck imports test test-network \
        web-lint web-test web-format web-format-check

help:
	@printf "%s\n" \
		"Targets:" \
		"  make install      Init submodules, build web, and install via uv tool" \
		"  make build        Build web frontend + Python package" \
		"  make build-web    Build web frontend only" \
		"  make lint         Run ruff + pyright + import-linter + web eslint" \
		"  make format       Auto-fix with ruff + prettier" \
		"  make test         Run tests (pytest + vitest)"

install:
	git submodule update --init --recursive
	$(UV) run python scripts/build_web.py
	$(UV) tool install -e .

build-web:
	$(UV) run python scripts/build_web.py

build: build-web
	$(UV) build

lint: ruff-check typecheck imports web-lint

ruff-check:
	$(RUFF) check .

format:
	$(RUFF) check --fix .
	$(RUFF) format .
	cd web && $(NPM) run format

format-check:
	$(RUFF) format --check .
	cd web && $(NPM) run format:check

typecheck:
	$(PYRIGHT)

imports:
	$(IMPORT_LINT)

web-lint:
	cd web && $(NPM) run lint

web-test:
	cd web && $(NPM) test

web-format:
	cd web && $(NPM) run format

web-format-check:
	cd web && $(NPM) run format:check

test: web-test
	$(PYTEST) -m "not network"

test-network:
	$(PYTEST) -m "network"