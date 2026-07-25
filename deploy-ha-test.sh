#!/usr/bin/env bash
# Deploy Wattson to ha-test (10.42.2.109)
set -euo pipefail

HA_TEST_HOST="ha-test"
HA_TEST_PATH="/var/lib/docker/volumes/hass_config/_data/custom_components/wattson"
SRC="$(dirname "$0")/custom_components/wattson"

echo "Deploying to $HA_TEST_HOST:$HA_TEST_PATH ..."
ssh "$HA_TEST_HOST" "mkdir -p $HA_TEST_PATH"
# __pycache__ ausschließen: lokal kompilierte .pyc gehören nicht ins Zielsystem,
# HA kompiliert selbst
rsync -av --delete --exclude='__pycache__' "$SRC/" "$HA_TEST_HOST:$HA_TEST_PATH/"
echo "Done. Restart Home Assistant to apply."
