#!/usr/bin/env bash
set -e

echo "================================================================================"
echo " RUNNING COMPLETE SYSTEM BENCHMARK"
echo "================================================================================"
sleep 10

DIR="$(dirname "$0")"

echo ""
echo "================================================================================"
echo " === RUNNING SESSION 8 GENERAL EVALUATION QUERIES ==="
echo "================================================================================"

echo ""
echo "=== Query Hello ==="
bash "$DIR/run_query.sh" hello
sleep 2

echo ""
echo "=== Query A ==="
bash "$DIR/run_query.sh" a
sleep 2

echo ""
echo "=== Query I ==="
bash "$DIR/run_query.sh" i
sleep 2

echo ""
echo "=== Query J ==="
bash "$DIR/run_query.sh" j
sleep 2

echo ""
echo "=== Query K ==="
bash "$DIR/run_query.sh" k
sleep 2

echo ""
echo "================================================================================"
echo " === RUNNING SESSION 8 CODE EVALUATION QUERIES ==="
echo "================================================================================"

echo ""
echo "=== Query Parallel Fan Out ==="
bash "$DIR/run_query.sh" parallel
sleep 2

echo ""
echo "=== Query Critic and Coder ==="
bash "$DIR/run_query.sh" coder_test
sleep 2

echo ""
echo "=== Query New Skill Indexer ==="
bash "$DIR/run_query.sh" indexer_test
sleep 2

echo ""
echo "================================================================================"
echo " ALL SYSTEM BENCHMARK RUNS COMPLETED SUCCESSFULLY!"
echo "================================================================================"
