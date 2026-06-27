#!/usr/bin/env bash
set -e

echo "================================================================================"
echo " RUNNING COMPUTER-USE SKILL BENCHMARK"
echo "================================================================================"
sleep 10

DIR="$(dirname "$0")"

echo ""
echo "=== Task: Calculator × Notes (zero vision) ==="
bash "$DIR/run_query.sh" task_calc_notes
sleep 2

echo ""
echo "=== Task: Obsidian (Electron / CDP) ==="
bash "$DIR/run_query.sh" task_obsidian
sleep 2

echo ""
echo "=== Task: Chess Board Description (vision) ==="
bash "$DIR/run_query.sh" task_vision2
sleep 2

echo ""
echo "================================================================================"
echo " ALL COMPUTER-USE BENCHMARK RUNS COMPLETED!"
echo "================================================================================"
