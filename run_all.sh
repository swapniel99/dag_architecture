#!/usr/bin/env bash
set -e

echo "================================================================================"
echo "LEXIS-RAG: RUNNING COMPLETE SYSTEM BENCHMARK (ALL QUERIES A TO I5)"
echo "================================================================================"
sleep 10

DIR="$(dirname "$0")"

echo ""
echo "================================================================================"
echo "=== RUNNING SESSION 7 GENERAL EVALUATION QUERIES ==="
echo "================================================================================"

echo ""
echo "=== Query A ==="
bash "$DIR/run_query.sh" a
sleep 2

echo ""
echo "=== Query B ==="
bash "$DIR/run_query.sh" b
sleep 2

echo ""
echo "=== Query C1 ==="
bash "$DIR/run_query.sh" c1
sleep 2

echo ""
echo "=== Query C2 ==="
bash "$DIR/run_query.sh" c2 --no-clear
sleep 2

echo ""
echo "=== Query D ==="
bash "$DIR/run_query.sh" d
sleep 2

echo ""
echo "=== Query E ==="
bash "$DIR/run_query.sh" e
sleep 2

echo ""
echo "=== Query F1 ==="
bash "$DIR/run_query.sh" f1
sleep 2

echo ""
echo "=== Query F2 ==="
bash "$DIR/run_query.sh" f2 --no-clear
sleep 2

echo ""
echo "=== Query G ==="
bash "$DIR/run_query.sh" g
sleep 2

echo ""
echo "=== Query H ==="
bash "$DIR/run_query.sh" h
sleep 2

echo ""
echo "================================================================================"
echo "=== RUNNING NEW INGESTION & SEMANTIC RECALL QUERIES ==="
echo "================================================================================"

bash "$DIR/clear_state.sh"

echo ""
echo "=== Preparing clean FAISS index for I-series queries ==="
uv run bulk_index.py
sleep 2

echo ""
echo "=== Query I1 (Direct Corporate - Index Dependent) ==="
bash "$DIR/run_query.sh" i1 --no-clear
sleep 2

echo ""
echo "=== Query I2 (Direct Real Estate - Index Dependent) ==="
bash "$DIR/run_query.sh" i2 --no-clear
sleep 2

echo ""
echo "=== Query I3a (Semantic Corporate - Zero Overlap) ==="
bash "$DIR/run_query.sh" i3a --no-clear
sleep 2

echo ""
echo "=== Query I3b (Semantic Corporate - Zero Overlap) ==="
bash "$DIR/run_query.sh" i3b --no-clear
sleep 2

echo ""
echo "=== Query I4 (Semantic Real Estate - Zero Overlap) ==="
bash "$DIR/run_query.sh" i4 --no-clear
sleep 2

echo ""
echo "=== Query I5 (Direct Corporate - Index Dependent) ==="
bash "$DIR/run_query.sh" i5 --no-clear

echo ""
echo "================================================================================"
echo "LEXIS-RAG: ALL SYSTEM BENCHMARK RUNS COMPLETED SUCCESSFULLY!"
echo "================================================================================"
