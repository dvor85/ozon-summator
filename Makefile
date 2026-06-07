SHELL := /bin/bash
# =============================================================================
# Variables
# =============================================================================
PYTHON := uv run
ALCHEMY := uv run alchemy --config core.database.alchemy_config
.DEFAULT_GOAL:=help
.ONESHELL:
.EXPORT_ALL_VARIABLES:
MAKEFLAGS += --no-print-directory

# Define colors and formatting
BLUE := $(shell printf "\033[1;34m")
GREEN := $(shell printf "\033[1;32m")
RED := $(shell printf "\033[1;31m")
YELLOW := $(shell printf "\033[1;33m")
NC := $(shell printf "\033[0m")
INFO := $(shell printf "$(BLUE)ℹ$(NC)")
OK := $(shell printf "$(GREEN)✓$(NC)")
WARN := $(shell printf "$(YELLOW)⚠$(NC)")
ERROR := $(shell printf "$(RED)✖$(NC)")

#Define global vars
GITLAB := "gitlab.com"
ROOT_DIR := $(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))
PROJECT_NAME := $(shell basename $(ROOT_DIR))
#PKG_TOKEN := $(shell uv auth token ${GITLAB})

.PHONY: help
help:                                               ## Показать эту справку для Makefile
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)


# =============================================================================
# Developer Utils
# =============================================================================
.PHONY: install-tools
install-tools:                                         ## Установить последнюю версию uv и инструменты
	@echo "${INFO} Installing uv..."
	@curl -LsSf https://astral.sh/uv/install.sh | sh
	@uv tool install ruff
	@uv tool install mypy
	@uv tool install pytest
	@echo "${OK} UV installed successfully"

.PHONY: upgrade-tools
upgrade-tools:                                            ## Обновить uv и инструменты
	@echo "${INFO} Updating uv... 🔄"
	@uv self update
	@uv tool upgrade ruff
	@uv tool upgrade mypy
	@uv tool upgrade pytest
	@echo "${OK} tools updated 🔄"

.PHONY: install
install: destroy clean                              ## Установить среду, зависимости для локальной разработки
	@echo "${INFO} Starting fresh installation..."
	@uv venv
	@uv sync --all-extras --dev
	@echo "${OK} Installation complete! 🎉"

.PHONY: upgrade
upgrade:                                            ## Обновить все зависимости до последних версий
	@echo "${INFO} Updating all dependencies... 🔄"
	@uv lock --upgrade
	@uv sync --all-extras --dev
	@echo "${OK} Dependencies updated 🔄"

.PHONY: requirements
requirements:									   ## Обновить requirements.txt
	@echo "${INFO} Updating requirements... 🦈"
	@uv export --format requirements.txt --no-dev --no-hashes --output-file requirements.txt > /dev/null
	@echo "${OK} Requirements updated"


.PHONY: build
build:                                             ## Собрать бинарник
	@echo "${INFO} Собрать бинарник... 🧪"
	@uv run pyinstaller main.spec
	@echo "${OK} Бинарник собран успешно ✨"


.PHONY: clean
clean:                                              ## Очистка кэша
	@echo "${INFO} Cleaning working directory..."
	@rm -rf pytest_cache .ruff_cache .hypothesis build/ -rf dist/ .eggs/ .coverage coverage.xml coverage.json htmlcov/ .pytest_cache tests/.pytest_cache tests/**/.pytest_cache .mypy_cache .unasyncd_cache/ .auto_pytabs_cache node_modules >/dev/null 2>&1
	@find . -name '*.egg-info' -exec rm -rf {} + >/dev/null 2>&1
	@find . -type f -name '*.egg' -exec rm -f {} + >/dev/null 2>&1
	@find . -name '*.pyc' -exec rm -f {} + >/dev/null 2>&1
	@find . -name '*.pyo' -exec rm -f {} + >/dev/null 2>&1
	@find . -name '*~' -exec rm -f {} + >/dev/null 2>&1
	@find . -name '__pycache__' -exec rm -rf {} + >/dev/null 2>&1
	@find . -name '.ipynb_checkpoints' -exec rm -rf {} + >/dev/null 2>&1
	@echo "${OK} Working directory cleaned"

.PHONY: destroy
destroy:                                            ## Уничтожить venv
	@echo "${INFO} Destroying virtual environment... 🗑️"
	@rm -rf .venv
	@echo "${OK} Virtual environment destroyed 🗑️"


# =============================================================================
# Tests, Linting, Coverage
# =============================================================================
.PHONY: lint
lint:                                              ## Запустить скрипты lint
	@echo "${INFO} Running linting... 🔍"
	@$(PYTHON) ruff format
	@$(PYTHON) ruff check --fix.
	@$(PYTHON) mypy .
	@echo "${OK} Lint checks passed ✨"

.PHONY: test
test:                                              ## Запустить тесты
	@echo "${INFO} Running test cases... 🧪"
	@$(PYTHON) pytest tests --quiet
	@echo "${OK} Tests passed ✨"

.PHONY: cov
cov:                                              ## Покрытие тестами
	@echo "${INFO} Running calculations... 🧪"
	@$(PYTHON) pytest --cov=app








