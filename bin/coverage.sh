#!/usr/bin/env bash
# Run the suite with coverage and print the summary.
#
# The summary and the gate are shared tooling from jmerhar/coverage, configured by
# coverage.toml, so the numbers here are the ones CI enforces.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

bin/coverage-tooling.sh

bin/test-backend.sh \
  --cov=ecowitt \
  --cov-report=term-missing \
  --cov-report=xml \
  --cov-report=json \
  --cov-report=html \
  -q

echo
python3 .coverage-report.py "$@"
