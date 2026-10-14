#!/usr/bin/env bash
# Create the GitHub release for a pushed tag, from its CHANGELOG.md section:
# bin/github-release.sh vX.Y.Z   (needs gh, authenticated with GH_TOKEN)
set -euo pipefail

cd "$(dirname "$0")/.."
tag="${1:?usage: bin/github-release.sh vX.Y.Z}"
version="${tag#v}"

python3 bin/version.py check "$tag"
python3 bin/version.py notes "$version" \
  | gh release create "$tag" --verify-tag --title "Ecowitt Server $version" --notes-file -
