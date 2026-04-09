#!/bin/bash
FILE_PATH=$(jq -r '.tool_input.file_path' < /dev/stdin)

if [[ "$FILE_PATH" == */router.py ]] || [[ "$FILE_PATH" == */clickhouse.py ]]; then
  if grep -nE 'f"(SELECT|INSERT|DELETE|UPDATE|ALTER|DROP)' "$FILE_PATH" 2>/dev/null; then
    echo "Possible raw f-string SQL detected -- use parameterized queries" >&2
  fi
fi

exit 0
