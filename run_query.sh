#!/usr/bin/env bash
set -e

QUERY_DIR="$(dirname "$0")/queries"

usage() {
    echo "Usage: $0 <query_id> [--no-clear]"
    echo "  query_id: a, b, c1, c2, d, e, f1, f2, f, g"
    echo "  --no-clear: skip state reset"
    exit 1
}

[[ $# -lt 1 ]] && usage

QUERY_ID="$1"
NO_CLEAR=0
[[ "$2" == "--no-clear" ]] && NO_CLEAR=1

QUERY_FILE="$QUERY_DIR/query_${QUERY_ID}.txt"

if [[ ! -f "$QUERY_FILE" ]]; then
    echo "Error: no query file for '$QUERY_ID' (looked for $QUERY_FILE)"
    exit 1
fi

QUERY="$(cat "$QUERY_FILE")"

if [[ $NO_CLEAR -eq 0 ]]; then
    bash "$(dirname "$0")/clear_state.sh"
fi

echo "Query [$QUERY_ID]: $QUERY"
echo ""

uv run python -u agent7.py "$QUERY"
