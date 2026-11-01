#!/usr/bin/env bash
# Double-click launcher for macOS (opens in Terminal): Hugging Face Model Radar & History.
exec "$(cd "$(dirname "$0")" && pwd)/../unix/radar.sh" "$@"

