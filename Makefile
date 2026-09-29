.DEFAULT_GOAL := help

UV ?= uv
PNPM ?= pnpm
KLAUDE ?= klaude

WEB_DIR := web

RUFF := $(UV) run ruff
TY := $(UV) run ty
IMPORT_LINT := $(UV) run lint-imports
PYTEST := $(UV) run pytest

.PHONY: help pre-push install web build lint ruff-check format format-check typecheck imports test test-network

help:
	@printf "%s\n" \
		"Targets:" \
		"  make pre-push     Run all formatting, linting, tests, and builds" \
		"  make install      Install package (editable) + web viewer, then reload the running server" \
		"  make web          Install web viewer deps and build the static bundle" \
		"  make build        Build Python package" \
		"  make lint         Run ruff + ty + import-linter" \
		"  make format       Auto-fix with ruff" \
		"  make format-check Check formatting without fixing" \
		"  make test         Run tests"

pre-push:
	$(MAKE) format
	$(MAKE) lint
	$(MAKE) test
	$(MAKE) build

install: web
	@echo "==> Syncing git submodules..."
	git submodule update --init --recursive
	@echo "==> Installing Python package (editable, via uv tool)..."
	$(UV) tool install -e .
	@echo "==> Restarting the running klaude server on the new code (if any)..."
	@if ! command -v $(KLAUDE) >/dev/null 2>&1; then \
		echo "error: '$(KLAUDE)' not found in PATH; cannot reload the server after install" >&2; \
		exit 1; \
	elif $(KLAUDE) server status >/dev/null 2>&1; then \
		$(KLAUDE) server reload --when-idle; \
	else \
		echo "klaude server is not running; it will start on the next klaude command"; \
	fi

web:
	@echo "==> Building web viewer bundle..."
	$(PNPM) --dir $(WEB_DIR) install
	$(PNPM) --dir $(WEB_DIR) build

build:
	$(UV) build

lint: ruff-check typecheck imports

ruff-check:
	$(RUFF) check .

format:
	$(RUFF) check --fix .
	$(RUFF) format .

format-check:
	$(RUFF) format --check .

typecheck:
	$(TY) check

imports:
	$(IMPORT_LINT)

test:
	$(PYTEST) -m "not network"

test-network:
	$(PYTEST) -m "network"
