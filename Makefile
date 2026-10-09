.PHONY: help install dev up down logs shell build test coverage lint check clean

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*##|^##@' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; /^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next} {printf "  \033[36mmake %-16s\033[0m %s\n", $$1, $$2}'

##@ Setup

install: ## Create the virtualenv and install the package with its test extras
	python3 -m venv backend/.venv
	backend/.venv/bin/pip install --quiet --upgrade pip
	backend/.venv/bin/pip install --quiet -e "backend[test]"
	@echo "Installed. 'make test' runs the suite, 'make dev' serves locally."

##@ Development

dev: ## Serve from the working copy with debug logging (ingest :2551, admin :2552)
	cd backend && DATA_DIR=../data LOG_LEVEL=DEBUG .venv/bin/python -m ecowitt

up: ## Build and start the stack
	docker compose -f docker-compose.yml -f docker-compose.build.yml up --build -d
	@echo "Status page: http://127.0.0.1:2552"

down: ## Stop the stack, keeping the data
	docker compose down

logs: ## Follow the container's log
	docker compose logs -f

shell: ## Open a shell in the running container
	docker compose exec ecowitt sh

build: ## Build the image without starting anything
	docker compose -f docker-compose.yml -f docker-compose.build.yml build

##@ Testing

test: ## Run the suite (arguments pass through to pytest, e.g. ARGS="-k slash")
	bin/test-backend.sh $(ARGS)

coverage: ## Run the suite with coverage and print the summary
	bin/coverage.sh --format md

lint: ## ShellCheck, ruff, and the compose files
	bin/lint.sh

check: lint test coverage ## Everything (gate a commit on this)

##@ Housekeeping

clean: ## Remove build and coverage artefacts (all regenerable)
	rm -rf backend/htmlcov backend/coverage.xml backend/coverage.json backend/.coverage \
	       backend/junit backend/.ruff_cache backend/.pytest_cache \
	       coverage-upload .coverage-report.py
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
