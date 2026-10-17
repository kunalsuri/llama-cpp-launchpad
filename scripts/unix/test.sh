#!/usr/bin/env bash
# Run the test suite (same runner CI uses). Extra arguments go to tests/run.py, e.g.  test.sh -k ollama --repeat 5
PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then echo "tests need Python 3.10+."; exit 1; fi
exec "$PY" "$(cd "$(dirname "$0")" && pwd)/../../tests/run.py" "$@"
