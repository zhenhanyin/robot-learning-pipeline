# Legacy source audit

This audit closes the source-inventory work for the three legacy areas without copying entire trees. “Migrated” means a new implementation with contract tests, not a byte-for-byte port. The source project contains duplicated backups, generated workspaces, binaries and dependencies that are not part of the new package.

| Source area | Treatment | Boundary |
| --- | --- | --- |
| Piper collection, synchronization and Qt data UI | Migrated to ROS1 capture adapter, Episode workflow and local operations/annotation UI | Vendor SDK is installed by the user; no old Qt source is copied |
| ARX status/image capture, legacy HDF5 import and replay | Migrated to ROS2 adapters, readers, explicit replay and training export | Units/action provenance remain config/data declarations; no driver or generated ROS workspace |
| ACT/H-RDT/π0/π0.5, speech, VLM and task workflows | Re-expressed as policy manifests, optional HTTP clients, task allowlist/approval and preview APIs | No checkpoints, Whisper/CosyVoice/LLM/VLM implementation or old pickle wire protocol |
| Old deployment Qt panel and remote control pages | Rebuilt as a local operations console and loopback ROS1 control adapter | The original `gui_4_2/lib/` modules were missing from the supplied tree; undocumented behavior cannot be reproduced as source-compatible APIs |
| ARX VR / Quest 3 | Rebuilt as a typed teleoperation boundary and fail-closed command gate | Proprietary ROS packages, `.so`, APK, hardware calibration and IK stay external |
| OpenPI, LLaMA-Factory, GR00T and other training frameworks | Use exported dataset formats, examples, manifests and external backend references | Upstream frameworks/patches/weights are not vendored; GR00T-specific support is not claimed |
| `祖传脚本/Preliminary`, setup notes, duplicate/copy/backup/unused trees | Reviewed as historical or redundant material; no unique supported runtime path identified | Retain only source references in this audit, not old screenshots, compiled files or documents |

The audit covers the supplied source tree as available locally on 2026-10-22. Device-specific service secrets, private packages, binary SDKs, Unity/Quest assets and any files absent from that tree are outside the migration claim. See [migration map](migration.md), [third-party inventory](../THIRD_PARTY_NOTICES.md), [operations console](operations-console.md), and [teleoperation boundary](teleoperation.md).
