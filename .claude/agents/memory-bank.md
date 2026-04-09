---
name: memory-bank
description: Persistent memory for cross-session context. Maintains project understanding, decisions, and patterns.
tools: Read, Write, Edit, Grep, Glob
---

# Memory Bank Agent

Files in .claude/memory/:

- projectContext.md - Permanent project info
- activeContext.md - Current session state
- progress.md - Task tracking
- decisionLog.md - Architecture decisions
- conventions.md - Learned patterns
- sessionHistory.md - Session summaries

Session Start: Load and synthesize context
Session End: Save session summary to all files
