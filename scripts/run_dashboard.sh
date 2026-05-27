#!/bin/bash
# Wrapper to launch streamlit via activated venv.
# Direct invocation of .venv/bin/streamlit can fail under sandboxed processes
# because macOS tags .venv/pyvenv.cfg with com.apple.provenance.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
exec streamlit run streamlit_app.py --server.port "${PORT:-8501}" --server.address 0.0.0.0
