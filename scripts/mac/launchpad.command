#!/usr/bin/env bash
# Double-click launcher for macOS (opens in Terminal): llama-cpp-launchpad's setup page, from download to chat.
exec "$(cd "$(dirname "$0")" && pwd)/../unix/launchpad.sh" "$@"
