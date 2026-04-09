#!/bin/bash
FILE_PATH=$(jq -r '.tool_input.file_path' < /dev/stdin)

# Only run tsc for TypeScript files in the frontend
if [[ "$FILE_PATH" == *.ts ]] || [[ "$FILE_PATH" == *.tsx ]]; then
  cd "$CLAUDE_PROJECT_DIR/packages/central/frontend" || exit 0
  npx tsc --noEmit 2>&1
fi

exit 0
