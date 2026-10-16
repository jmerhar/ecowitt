.PHONY: help install web-install lockfile app-icons grafana messages dev dashboard-dev up down logs shell build test test-js test-web test-legacy-browser test-bruno coverage lint check release clean

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*##|^##@' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; /^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next} {printf "  \033[36mmake %-16s\033[0m %s\n", $$1, $$2}'

##@ Setup

install: ## Create the shared virtualenv and install every project with its test extras
	python3 -m venv .venv
	.venv/bin/pip install --quiet --upgrade pip
	.venv/bin/pip install --quiet -e "core[test]" -e "collector[test]" -e "dashboard/api[test]"
	@echo "Installed. 'make test' runs the suite, 'make dev' serves locally."

web-install: ## Install the dashboard pages' node_modules from the lockfile (needs Node 24)
	cd dashboard/web && npm ci --no-audit --no-fund --registry="$$(cd / && npm config get registry)"

lockfile: ## Regenerate the pages' package-lock.json (Linux binaries, public registry URLs)
	bin/lockfile.sh

app-icons: ## Render the dashboard's home-screen icons from dashboard/web/icons/app-icon.svg
	bin/app-icons.sh

grafana: ## Render grafana/weather.json and alerts.json from the templates in the collector package
	.venv/bin/python bin/grafana.py

messages: ## Bring the dashboard API's translation catalogues up to date with its messages
	.venv/bin/python bin/messages.py

##@ Development

dev: ## Serve the collector from the working copy, debug logging (ingest :2551, admin :2552)
	DATA_DIR=data LOG_LEVEL=DEBUG .venv/bin/python -m ecowitt.collector

dashboard-dev: ## Serve the dashboard, reloading (page :5173, API :2553); SERVER=host for its InfluxDB
	bin/dashboard-dev.sh $(SERVER)

up: ## Build and start the stack, the dashboard included
	docker compose -f docker-compose.yml -f docker-compose.build.yml --profile dashboard up --build -d
	@echo "Status page: http://127.0.0.1:2552  Dashboard: http://127.0.0.1:2553"

down: ## Stop the stack, keeping the data
	docker compose --profile dashboard down

logs: ## Follow the containers' logs
	docker compose --profile dashboard logs -f

shell: ## Open a shell in the running collector container
	docker compose exec ecowitt sh

build: ## Build both images without starting anything
	docker compose -f docker-compose.yml -f docker-compose.build.yml --profile dashboard build

##@ Testing

test: ## Run the Python suites (ARGS pass through to pytest, e.g. ARGS="-k slash")
	bin/test-python.sh core $(ARGS)
	bin/test-python.sh collector $(ARGS)
	bin/test-python.sh dashboard/api $(ARGS)

test-js: ## Run the page script tests with coverage (needs node)
	bin/test-js.sh

test-web: ## Type-check and test the dashboard pages with coverage (after make web-install)
	bin/test-web.sh

test-legacy-browser: ## Load the pages' legacy build in Chromium 59 (needs Docker; slow off x64)
	bin/test-legacy-browser.sh

test-bruno: ## Run the Bruno collection's dashboard requests against the API over test data (needs Node)
	bin/test-bruno.sh

coverage: ## Run every suite with coverage and print the summary
	bin/coverage.sh --format md

lint: ## ShellCheck, ruff, the lockfile's registry, the versions, and the compose files
	bin/lint.sh

check: lint coverage ## Everything (gate a commit on this; coverage runs every suite)

##@ Releasing

release: ## Cut release VERSION=X.Y.Z: version the manifests, date the changelog, commit and tag
	bin/release.sh $(VERSION)

##@ Housekeeping

clean: ## Remove build and coverage artefacts (all regenerable)
	rm -rf */htmlcov */coverage.xml */coverage.json */.coverage */coverage-js \
	       dashboard/web/coverage dashboard/web/dist \
	       */junit .ruff_cache */.pytest_cache \
	       dashboard/api/htmlcov dashboard/api/coverage.xml dashboard/api/coverage.json \
	       dashboard/api/.coverage dashboard/api/junit dashboard/api/.pytest_cache \
	       coverage-upload .coverage-report.py
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
