#!/bin/bash
# Run the collector service continuously
# Usage: ./scripts/run_collector.sh

cd /home/kyi/LuminaV2/bsc-analyzer
source /home/kyi/LuminaV2/lumina-backend/.venv/bin/activate

echo "Starting Lumina BSC Collector..."
echo "Press Ctrl+C to stop"

python services/collector.py
