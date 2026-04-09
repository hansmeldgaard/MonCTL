#!/bin/bash
FILE_PATH=$(jq -r '.tool_input.file_path' < /dev/stdin)

if [[ "$FILE_PATH" == */storage/models.py ]]; then
  echo "models.py was modified -- remember to create an Alembic migration if you changed the schema." >&2
fi

exit 0
