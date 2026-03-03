# Infrastructure Discovery

Run the Phase 0.1 auto-discovery script to map all nodes.

## Steps

1. Run `bash scripts/discover.sh` from the project root
2. Review the generated `docs/infrastructure-report.md`
3. Update Ansible inventory with discovered IPs
4. Identify any discrepancies with the plan
5. Report findings in a summary

## When to Use

- After initial DEV setup (first run)
- After hardware changes (GPU moves, RAM swaps, new drives)
- After network changes (IP reassignment, new nodes)
- Before any Phase 1+ deployment to confirm current state
