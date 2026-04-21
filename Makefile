.DEFAULT_GOAL := help

UV ?= uv
NPM := $(if $(shell command -v pnpm 2>/dev/null),pnpm,npm)

RUFF := $(UV) run ruff
TY := $(UV) run ty
IMPORT_LINT := $(UV) run lint-imports
PYTEST := $(UV) run pytest

.PHONY: help install install-python install-web build build-web lint ruff-check format format-check typecheck imports \
        test test-network web-lint web-test web-format web-format-check

help:
	@printf "%s\n" \
		"Targets:" \
		"  make install      Install Python package first, then build web frontend" \
		"  make build        Build web frontend + Python package" \
		"  make build-web    Build web frontend only" \
		"  make lint         Run ruff + ty + import-linter + web eslint" \
		"  make format       Auto-fix with ruff + prettier" \
		"  make test         Run tests (pytest + vitest)"

install: install-python install-web

install-python:
	@echo "==> Syncing git submodules..."
	git submodule update --init --recursive
	@echo "==> Installing Python package (editable, via uv tool)..."
	$(UV) tool install -e .

install-web:
	@echo "==> Building web frontend..."
	$(UV) run python scripts/build_web.py || echo "WARNING: web build failed, Python package is still usable"

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
	$(TY) check

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