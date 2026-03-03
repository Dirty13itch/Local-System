# Autonomous Build Session

Execute one focused build session. Follow this protocol strictly.

## Protocol

### 1. Orient (< 2 min)
- Read `docs/infrastructure-report.md` for current hardware state
- Check `git log --oneline -10` for recent work
- Identify the highest-priority incomplete phase from the plan

### 2. Research (as needed)
- Read relevant files before modifying
- Check reference repos for patterns: `/opt/reference/athanor/`, `/opt/reference/kaizen/`
- Understand existing code before changing it

### 3. Build
- Work on ONE phase or sub-task at a time
- Test as you go — don't batch testing to the end
- Follow the Tüftler Principle: refine what works, don't restart

### 4. Verify
- Run tests: `python -m pytest tests/ -v`
- Check service health if applicable: `bash scripts/health-check.sh`
- Verify Docker builds: `docker compose -f deploy/<node>/docker-compose.yml config`

### 5. Document
- Write an ADR for any significant technical decision (`docs/decisions/`)
- Update CLAUDE.md if architecture changed
- Update infrastructure-report.md if hardware assignment changed

### 6. Commit
- Commit with clear message describing what and why
- Push to the working branch

### 7. Continue or Stop
- If time/context allows, start next priority task
- If blocked on Shaun (credentials, physical, money), document the blocker and stop

## Decision Rules
- P0 > P1 > P2 > P3 priority
- Depth over breadth (finish one thing before starting another)
- Right over fast (quality matters)
