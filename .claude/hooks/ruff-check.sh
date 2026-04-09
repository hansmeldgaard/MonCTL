#!/bin/bash
FILE_PATH=$(jq -r '.tool_input.file_path' < /dev/stdin)

if [[ "$FILE_PATH" == *.py ]]; then
  ~/.local/bin/ruff check "$FILE_PATH" 2>&1
fi

exit 0
