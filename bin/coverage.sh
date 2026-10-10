#!/usr/bin/env bash
# Run every suite with coverage and print the summary.
#
# The summary and the gate are shared tooling from jmerhar/coverage, configured by
# coverage.toml, so the numbers here are the ones CI enforces.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

bin/coverage-tooling.sh

bin/test-python.sh collector \
  --cov=ecowitt.collector \
  --cov-report=term-missing \
  --cov-report=xml \
  --cov-report=json \
  --cov-report=html \
  -q

bin/test-js.sh

echo
python3 .coverage-report.py "$@"
