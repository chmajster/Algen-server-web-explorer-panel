# Proxmox Advanced 361–380

The existing Proxmox Manager now exposes an **Advanced 361–380** section. It reuses the same Proxmox API connections, encrypted Hosts Manager credentials, RBAC model and Activity Center audit trail.

## Scope

| # | Feature | Implementation |
|---|---|---|
| 361 | Cluster Health | quorum, cluster status, Corosync config, nodes, storage pressure, HA status |
| 362 | VM Placement Advisor | CPU/RAM/storage fit and weighted target-node score |
| 363 | Capacity Planner | estimated remaining VM count from requested vCPU/RAM/disk profile |
| 364 | Storage Balancer | storage pressure plus VM movement candidates |
| 365 | Backup Analyzer | vzdump/PBS backup inventory, jobs and VM coverage gaps |
| 366 | PBS Manager | PVE-integrated PBS datastore/snapshot/backup-job visibility |
| 367 | Replication Manager | cluster ZFS replication jobs |
| 368 | HA Manager | HA groups, resources and current state |
| 369 | Migration Planner | source/target preview and live-migration indication |
| 370 | Network Planner | node bridges, bonds and VLAN-aware interfaces |
| 371 | SDN Manager | zones, VNets, subnets and controllers |
| 372 | Cloud-Init Profiles | persistent reusable provisioning profiles plus detected cloud-init VMs |
| 373 | VM Policy Manager | naming regex, required tags, vCPU/RAM limits and backup requirement |
| 374 | Orphan Detector | storage volumes that reference missing VMIDs |
| 375 | Snapshot Retention | old-snapshot discovery and explicitly confirmed cleanup |
| 376 | Guest Agent Audit | QGA configured/responding audit |
| 377 | Template Lifecycle | template metadata, version tags and cloud-init indication |
| 378 | ISO Lifecycle | ISO inventory and age-based cleanup candidates |
| 379 | VM Drift Manager | persistent expected configuration baselines versus live config |
| 380 | Bulk Operations | start, shutdown, reboot, force-stop, snapshot and migrate |

## API

Read operations require the existing Hosts Manager view permission.

```text
GET /api/modules/proxmox-manager/advanced/catalog
GET /api/modules/proxmox-manager/advanced/reports/{feature}
```

Report parameters include `connection_id`; placement/capacity reports additionally accept `cpu_cores`, `memory_mb` and `disk_gb`, while lifecycle reports accept `max_age_days`.

Configuration and destructive operations require the existing Hosts Manager host-management permission.

```text
POST   /api/modules/proxmox-manager/advanced/cloud-init-profiles
DELETE /api/modules/proxmox-manager/advanced/cloud-init-profiles/{name}
POST   /api/modules/proxmox-manager/advanced/vm-policies
DELETE /api/modules/proxmox-manager/advanced/vm-policies/{name}
POST   /api/modules/proxmox-manager/advanced/drift-baselines
DELETE /api/modules/proxmox-manager/advanced/drift-baselines/{vmid}
POST   /api/modules/proxmox-manager/advanced/snapshot-retention/apply
POST   /api/modules/proxmox-manager/advanced/bulk
```

## Safety model

Snapshot-retention deletion requires the exact confirmation text `DELETE OLD SNAPSHOTS`.

Bulk operations require the exact confirmation text `BULK <ACTION>`, for example `BULK SHUTDOWN` or `BULK MIGRATE`. Migration also requires a target node. Every mutation is recorded in Activity Center.

Placement and capacity results are advisory. The capacity formula uses the tightest of free CPU, free RAM and free storage against the requested VM shape and intentionally does not invent an HA reservation or overcommit policy.

## PBS boundary

A Proxmox VE API token can expose PVE-integrated PBS storage and backup content, but it is not a Proxmox Backup Server administrator credential. Therefore this version exposes PBS datastores, snapshots and PVE backup jobs through the existing Proxmox connection, while direct PBS `verify`, `prune` and PBS-to-PBS `sync` execution is not proxied. Those actions require a dedicated PBS API connection/credential model rather than reusing a PVE token with broader semantics than it actually has.
