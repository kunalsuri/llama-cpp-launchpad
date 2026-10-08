#!/usr/bin/env bash
# Opens the simple model setup page in your browser (localhost only). Ctrl+C stops it.
exec "$(cd "$(dirname "$0")" && pwd)/model-setup.sh" --ui "$@"
