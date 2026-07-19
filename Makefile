.DEFAULT_GOAL := help

UV ?= uv
NPM := $(if $(shell command -v pnpm 2>/dev/null),pnpm,npm)

RUFF := $(UV) run ruff
TY := $(UV) run ty
IMPORT_LINT := $(UV) run lint-imports
PYTEST := $(UV) run pytest

.PHONY: help pre-push pre-push-python install install-python install-web build python-build build-web lint \
        python-lint ruff-check format python-format format-check python-format-check typecheck imports test \
        python-test test-network web-lint web-test web-format web-format-check

help:
	@printf "%s\n" \
		"Targets:" \
		"  make pre-push     Run all formatting, linting, tests, and builds" \
		"  make pre-push-python Run Python-only pre-push checks" \
		"  make install      Install Python package first, then build web frontend" \
		"  make build        Build web frontend + Python package" \
		"  make lint         Run ruff + ty + import-linter + web eslint" \
		"  make format       Auto-fix with ruff + prettier" \
		"  make test         Run tests (pytest + vitest)" \
		"  make python-build Build Python package only" \
		"  make python-lint  Run Python lint, type, and import checks only" \
		"  make python-format Auto-fix Python formatting only" \
		"  make python-test  Run Python tests only" \
		"  make build-web    Build web frontend only"

pre-push:
	$(MAKE) format
	$(MAKE) lint
	$(MAKE) test
	$(MAKE) build

pre-push-python:
	$(MAKE) python-format
	$(MAKE) python-lint
	$(MAKE) python-test
	$(MAKE) python-build

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
	$(MAKE) python-build

python-build:
	$(UV) build

lint: python-lint web-lint

python-lint: ruff-check typecheck imports

ruff-check:
	$(RUFF) check .

format: python-format web-format

python-format:
	$(RUFF) check --fix .
	$(RUFF) format .

format-check: python-format-check web-format-check

python-format-check:
	$(RUFF) format --check .

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

test: web-test python-test

python-test:
	$(PYTEST) -m "not network"

test-network:
	$(PYTEST) -m "network"