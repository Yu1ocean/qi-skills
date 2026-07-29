#!/usr/bin/env bash
# Sensight Skill — initialize Client ID
# Idempotent: if the file exists, print it; otherwise generate a new UUID.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
ID_FILE="$HOME/.sensight/.sensight_client_id"

if [ -f "$ID_FILE" ]; then
  cat "$ID_FILE"
else
  if command -v uuidgen &>/dev/null; then
    NEW_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
  elif command -v python3 &>/dev/null; then
    NEW_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
  elif command -v python &>/dev/null; then
    NEW_ID=$(python -c "import uuid; print(uuid.uuid4())")
  else
    echo "ERROR: unable to generate a UUID. Please install uuidgen or python3." >&2
    exit 1
  fi
  mkdir -p "$(dirname "$ID_FILE")"
  echo "$NEW_ID" > "$ID_FILE"
  echo "$NEW_ID"
fi
