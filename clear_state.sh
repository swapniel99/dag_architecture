#!/bin/bash
echo "Clearing state in directory: $PWD"

rm -rf state/index.faiss state/*.json state/artifacts/ state/sessions/s8-* sandbox/*.md

echo "State cleared."
