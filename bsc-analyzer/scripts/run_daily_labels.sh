#!/bin/bash
# Daily label worker - run via cron
# Crontab entry: 0 0 * * * /home/kyi/LuminaV2/bsc-analyzer/scripts/run_daily_labels.sh

cd /home/kyi/LuminaV2/bsc-analyzer
source /home/kyi/LuminaV2/lumina-backend/.venv/bin/activate

echo "$(date): Starting daily label worker..."
python ml/label_worker.py

echo "$(date): Retraining model with new labels..."
python ml/simple_train.py

echo "$(date): Done!"
