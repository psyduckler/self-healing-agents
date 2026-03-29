#!/usr/bin/env bash
# demo.sh — Demonstrates self-healing-agents in action.
# Run from the repo root: bash demo/demo.sh

set -e
cd "$(dirname "$0")/.."

echo "=== Self-Healing Agents Demo ==="
echo ""

echo "$ self-heal version"
self-heal version
echo ""

echo "--- Scanning for failures ---"
echo "$ self-heal scan --config demo/demo-config.yaml --hours 24"
self-heal scan --config demo/demo-config.yaml --hours 24
echo ""

echo "--- Checking a known error ---"
echo '$ self-heal check "FileNotFoundError: /tmp/compare-shell-template.json"'
self-heal check "FileNotFoundError: /tmp/compare-shell-template.json"
echo ""

echo "--- Checking an unknown error ---"
echo '$ self-heal check "ConnectionRefusedError: [Errno 61] Connection refused"'
self-heal check "ConnectionRefusedError: [Errno 61] Connection refused"
echo ""

echo "--- Logging a new fix ---"
echo '$ self-heal log --error "ConnectionRefusedError on port 3000" --cause "API server not started" --fix "Added health check + auto-restart to systemd unit" --fix-type heal'
self-heal log --error "ConnectionRefusedError on port 3000" --cause "API server not started" --fix "Added health check + auto-restart to systemd unit" --fix-type heal
echo ""

echo "--- Stats ---"
echo "$ self-heal stats"
self-heal stats
echo ""

echo "--- Risk Assessment ---"
echo '$ self-heal risk "Modifying production deployment pipeline config"'
self-heal risk "Modifying production deployment pipeline config"
echo ""

echo "=== Demo complete ==="
