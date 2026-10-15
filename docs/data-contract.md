# Data contract v0 (draft)

## Required metadata for each episode

| Field | Meaning |
| --- | --- |
| `schema_version` | Episode 格式版本；与软件版本分开维护 |
| `robot_model` / `arm_id` | 设备型号与机械臂标识 |
| `timestamp_ns` / `clock_domain` | 纳秒时间戳及其时钟来源 |
| `joint_units` / `gripper_units` | 关节和夹爪单位 |
| `pose_frame` | 末端位姿所在坐标系及四元数顺序 |
| `action_source` | 主臂命令、从臂命令、下一状态或模型预测 |
| `camera_ids` / `camera_encoding` | 视角名和图像编码 |
| `sampling_hz` / `sync_tolerance_ms` | 目标采样率及同步容忍误差 |
| `software_version` | 产生该 episode 的软件版本 |

公共相机语义采用 `base`、`wrist_left`、`wrist_right`。具体 ROS Topic 在设备配置中映射。单臂数据保持原始维度，不在原始记录中填充不存在的另一只手臂。

`ArmState` 记录实际设备状态；`ArmAction` 记录训练目标和来源，并强制声明 `ActionSource`。`RobotCommand` 是独立类型，只有它能送给 `RobotAdapter.send_command()`。`NEXT_STATE` 仅用于把相邻状态构造为训练目标；不能被当成已经发送到控制器的命令。现有 ARX 的 `joint_action` 和 Piper 的 `leader_joint` / `follower_joint` 的具体语义，必须在迁移时逐条确认。

`CameraFrame.payload` 表示有编码信息的单帧图像。v0.0.2 的离线 JSONL 布局是独立的试验格式，详见 [离线格式说明](offline-episode.md)；未覆盖上表全部目标元数据，也不承诺与旧 HDF5 格式直接互换。Piper 第一批真机迁移时再核对单位、时钟和图像编码。
