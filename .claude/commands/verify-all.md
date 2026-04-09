---
description: Run tests, types, lint, build
---

!`npm test 2>&1 | tail -20 || echo "TESTS: CHECK"`
!`npm run typecheck 2>&1 || echo "TYPES: FAILED"`
!`npm run lint 2>&1 | tail -10 || echo "LINT: FAILED"`
!`npm run build 2>&1 | tail -10 || echo "BUILD: FAILED"`
