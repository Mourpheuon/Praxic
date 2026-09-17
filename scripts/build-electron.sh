#!/usr/bin/env bash
# Compatibility wrapper; native platform only, no automatic publication.
set -euo pipefail
if [ "$#" -gt 0 ]; then
    echo "Options retired. Cross-platform releases use the GitHub tag workflow." >&2
    exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "${PRAXIC_PYTHON:-python3}" "$SCRIPT_DIR/build_desktop.py"
