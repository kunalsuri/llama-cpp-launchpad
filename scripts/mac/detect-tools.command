#!/usr/bin/env bash
# Double-click launcher for macOS (opens in Terminal). Runs the shared Linux/macOS detect-tools script.
"$(cd "$(dirname "$0")" && pwd)/../unix/detect-tools.sh" "$@"
echo; read -n 1 -s -r -p "Press any key to close..."
