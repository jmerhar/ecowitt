#!/usr/bin/env bash
# Regenerate dashboard/web/package-lock.json.
#
# Two things this does that a plain `npm install` does not:
#
#  1. It installs inside a Linux container, matching CI and the image the pages are built in, so
#     the lockfile records the native packages that build needs. A lockfile written on macOS pins
#     darwin builds of Vite's bundler, and `npm ci` on Linux then has to resolve them again.
#  2. It rewrites every resolved URL to the public registry. On a network that proxies npm, the
#     lockfile otherwise records that proxy's hostname on every line -- and this repository is
#     published.
set -euo pipefail

web="$(cd "$(dirname "$0")/../dashboard/web" && pwd)"
public="https://registry.npmjs.org/"

# The registry npm is configured to reach outside this project, whose .npmrc names the public
# one: the install has to go through whatever this machine can reach.
registry=$(cd / && npm config get registry 2>/dev/null || echo "$public")

echo "Installing through: $registry"
echo "Recording:          $public"

rm -f "$web/package-lock.json"
# The project's .npmrc goes in for its other settings (the minimum release age); the registry
# given on the command line overrides its registry line.
docker run --rm \
  -v "$web/package.json:/app/package.json" \
  -v "$web/.npmrc:/app/.npmrc:ro" \
  -v "$web:/output" \
  -w /app \
  node:24-alpine \
  sh -c "npm install --registry='$registry' --no-fund --no-audit --loglevel=error && cp package-lock.json /output/package-lock.json"

# A proxied registry records URLs of the form https://<host>/artifactory/api/npm/npm/<pkg>.
# The pattern is shaped around the path rather than any particular hostname.
sed -i '' -E 's|https://[^"]+/artifactory/api/npm/[^/]+/|'"$public"'|g' "$web/package-lock.json"

"$(dirname "$0")/check-lockfile.sh"
echo "Lockfile regenerated."
