# ADR-001: Base Platform — Ubuntu 24.04 + Docker Compose + Ansible

**Status:** Accepted
**Date:** 2026-03-03
**Context:** Carried forward from Athanor ADR-001. Fourth iteration of this system (Hydra → Kaizen → Athanor → Local-System). Each iteration evaluated the base platform; this decision has been validated across all four.

## Decision

Ubuntu 24.04 LTS + Docker Compose + Ansible for all server nodes (FOUNDRY, WORKSHOP, VAULT, DEV). VAULT may run Unraid (to be confirmed by Phase 0.1 auto-discovery).

## Alternatives Considered

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Ubuntu 24.04 + Docker Compose** | Same-day NVIDIA drivers, one-person debuggable, `docker logs`/`docker exec` | Manual service management | **Chosen** |
| NixOS + Docker | Reproducible, declarative | CUDA packages lag weeks-months, steep learning curve | Rejected (Hydra/Kaizen) |
| Talos Linux + K8s | Immutable OS, GitOps | Couples OS to orchestration, quorum node never deployed | Rejected (Kaizen) |
| Proxmox | VM isolation | Unnecessary hypervisor layer for pinned workloads | Rejected |
| Kubernetes (any base) | Industry standard, scaling | Complexity without benefit for 4-6 fixed nodes | Rejected (Athanor) |
| Debian 12 | Stable | Weaker NVIDIA documentation, slower package updates | Rejected |

## Consequences

- NVIDIA driver installation is: PPA → apt install → NVIDIA CTK → docker run --gpus
- One `docker-compose.yml` per node
- Ansible for consistent base config across heterogeneous nodes
- All debugging uses standard Linux tools

## References

- Athanor ADR-001: `/opt/reference/athanor/docs/decisions/ADR-001-base-platform.md`
- Ubuntu 24.04.4 LTS released Feb 12, 2026 (HWE kernel 6.17)
- Docker Engine v29.2.1 (containerd image store default)
- Ansible-core 2.20.3 (requires Python >= 3.12)
