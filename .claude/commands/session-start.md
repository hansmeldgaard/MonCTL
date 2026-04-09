---
description: Load Memory Bank and orient to project
---

!`cat .claude/memory/projectContext.md 2>/dev/null | head -30 || echo "Run /memory-init"`
!`cat .claude/memory/activeContext.md 2>/dev/null | head -20`
!`cat .claude/memory/sessionHistory.md 2>/dev/null | head -30`
!`git status --short 2>/dev/null`
Synthesize context and ask what to work on.
