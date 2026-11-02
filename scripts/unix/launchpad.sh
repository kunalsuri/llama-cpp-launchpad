#!/usr/bin/env bash
# llama-cpp-launchpad: the one launcher. Opens the setup page in your browser (localhost only), where you can
# get llama.cpp, pick and download a model, and start chatting. Ctrl+C in this window stops the page.
exec "$(cd "$(dirname "$0")" && pwd)/model-setup.sh" --ui "$@"
