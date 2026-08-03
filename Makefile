.DEFAULT_GOAL := help

UV ?= uv

RUFF := $(UV) run ruff
TY := $(UV) run ty
IMPORT_LINT := $(UV) run lint-imports
PYTEST := $(UV) run pytest

.PHONY: help pre-push install build lint ruff-check format format-check typecheck imports test test-network

help:
	@printf "%s\n" \
		"Targets:" \
		"  make pre-push     Run all formatting, linting, tests, and builds" \
		"  make install      Install Python package (editable, via uv tool)" \
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

install:
	@echo "==> Syncing git submodules..."
	git submodule update --init --recursive
	@echo "==> Installing Python package (editable, via uv tool)..."
	$(UV) tool install -e .

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
