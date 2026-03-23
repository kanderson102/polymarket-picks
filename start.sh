#!/bin/bash

# Run any pending DB migrations/fixes (idempotent - safe to re-run)
echo "Running DB migrations..."
python3 fix_slugs.py

# Start the Python bot in the background
echo "Starting Polymarket Specialist Copy-Bot..."
python3 bot.py &

# Start the Streamlit Dashboard in the foreground
# Binding to 0.0.0.0 allows it to be accessed externally via the server's IP
echo "Starting Streamlit Dashboard on port 8501..."
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
