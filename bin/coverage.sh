#!/usr/bin/env bash
# Run every suite with coverage and print the summary.
#
# The summary and the gate are shared tooling from jmerhar/coverage, configured by
# coverage.toml, so the numbers here are the ones CI enforces.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

bin/coverage-tooling.sh

# One run per Python project, each measuring only its own package: core must reach its gate
# through its own tests, not through the collector's.
for project in core collector; do
  bin/test-python.sh "$project" \
    --cov="ecowitt.$project" \
    --cov-report=term-missing \
    --cov-report=xml \
    --cov-report=json \
    --cov-report=html \
    -q
done

bin/test-js.sh

echo
python3 .coverage-report.py "$@"
