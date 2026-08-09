# AssemblyVision Operational Runbooks

These runbooks implement the mandatory scenarios in the
[deployment and operations contract](../contracts/07-deployment-observability-and-operations.md).
Site-specific contacts, commands, thresholds, and hardware steps must be added during deployment.

| Scenario | Runbook |
|---|---|
| Camera disconnection | [01 - Camera Disconnection](01-camera-disconnection.md) |
| Model-loading failure | [02 - Model-Loading Failure](02-model-loading-failure.md) |
| Low disk space | [03 - Low Disk Space](03-low-disk-space.md) |
| Upload backlog | [04 - Upload Backlog](04-upload-backlog.md) |
| Database recovery | [05 - Database Recovery](05-database-recovery.md) |
| Repeated container restart | [06 - Repeated Container Restart](06-repeated-container-restart.md) |
| Synchronization after network recovery | [07 - Network Recovery Synchronization](07-network-recovery-synchronization.md) |
| Model rollback | [08 - Model Rollback](08-model-rollback.md) |
| Rule rollback | [09 - Rule Rollback](09-rule-rollback.md) |
| Model improvement | [10 - Model Improvement](10-model-improvement.md) |
| Data collection and annotation | [11 - Data Collection and Annotation](11-data-collection-and-annotation.md) |
| Backup and recovery | [12 - Backup and Recovery](12-backup-and-recovery.md) |
| TLS certificate rotation | [13 - TLS Certificate Rotation](13-tls-certificate-rotation.md) |
| Deployment upgrade and rollback | [14 - Deployment Upgrade and Rollback](14-deployment-upgrade-rollback.md) |

Every execution records device/site, start/end time, actor, affected inspections, evidence/log bundle,
actions, result, and escalation reference. A runbook never converts incomplete evidence to `OK`.
