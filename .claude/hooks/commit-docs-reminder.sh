#!/bin/bash
# After a git commit, remind to update CLAUDE.md/SYSTEM.md if architecture changed.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

# Only trigger on actual git commit commands (not git status, git diff, etc.)
if echo "$COMMAND" | grep -qE '^git commit\b'; then
  echo '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"Remember to update CLAUDE.md/SYSTEM.md if this commit changed the architecture, added new subsystems, or modified conventions."}}'
fi
