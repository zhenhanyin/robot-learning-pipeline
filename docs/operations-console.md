# Operator console

`robot-learning operations` serves a single loopback UI for read-only capture sessions, Episode validation/catalog browsing, frame annotation, and task proposals. It mounts the existing annotation assets and API, so the separate annotator server is not required.

```bash
mkdir -p ./data
python -m pip install -e .
robot-learning operations --data-root ./data \
  --profiles configs/operations_profiles.example.json --port 8768
```

Open `http://127.0.0.1:8768/`. Profiles point to local Piper/ARX configs; review every SDK module, ROS topic, CAN interface and unit before starting a capture. Replace example values with the authorized device setup. The console starts only `collect-piper` or `collect-arx` capture commands, neither is a motion command. Piper SDK initialization may still open CAN and emit its documented capability/firmware queries; see [Piper ROS1 collection](piper-ros1-collection.md).

Starting a capture creates a fresh directory under `data_root/recordings/` and writes subprocess output under `data_root/operations-logs/`. Stopping sends SIGINT to that capture process group, then escalates to termination only if it does not exit. It does not stop or brake a robot. Validate each resulting Episode before training. The profile JSON accepts at most 32 profiles with IDs and robot kinds from an allowlist; it cannot provide arbitrary shell commands.

## Annotation and task workflow

The episode list reports integrity, frame count and annotation count. The linked annotator edits the same `annotation.json` through the mounted API. Browser recording sends at most 1 MiB to the injected speech recognizer; this requires microphone permission and a local or HTTPS-configured service.

To enable task proposal/approval/preview, provide a trusted factory that returns a configured `TaskOrchestrator`:

```bash
robot-learning operations --data-root ./data \
  --profiles configs/operations_profiles.example.json \
  --task-factory my_robot_app:create_orchestrator
```

The UI allows text/audio proposal, human approval, offline candidate preview, and local runner stop. It deliberately has no `/api/tasks/execute` endpoint. The stop button is not a hardware emergency stop. A factory is imported and executed by the server process; only point it at code you trust.

The server binds `127.0.0.1`, validates the Host and same-origin headers, bounds requests, and serves no third-party scripts. It does not expose an authentication mechanism for remote users and must not be rebound to a LAN/public interface.
