# CLI and configuration design

`v0.1.0` 至 `v0.5.0` 分阶段提供采集、导出、策略预览和合成任务演示；`v0.6.0` 新增旧 HDF5/视频数据预处理及显式控制适配器。实时采集和命令发布需要对应外部 SDK/ROS；重组版尚未真机复测。离线命令用法见 README 和[数据预处理](data-preprocessing.md)。

| 命令 | 用途 | 最早阶段 |
| --- | --- | --- |
| `robot-learning doctor-piper --config configs/piper_ros1.json` | 静态检查 Python 依赖与 CAN 接口存在性，不连接设备 | P1 |
| `robot-learning collect-piper --config configs/piper_ros1.json ./data/run-001` | 用外部 SDK/ROS1 采集一条 Episode，不下发运动指令 | P1 |
| `robot-learning annotate --data-root ./data` | 启动仅绑定回环地址的离线标注服务 | P1c |
| `robot-learning doctor-arx --config configs/arx_x5_ros2.json` | 静态检查 ROS2/ARX 消息模块存在性，不连接设备 | P2 |
| `robot-learning collect-arx --config configs/arx_x5_ros2.json ./data/arx-run` | 只读订阅从臂状态与相机，不发布命令 | P2 |
| `robot-learning replay-arx-messages --config configs/arx_x5_ros2.json messages.jsonl ./data/arx-replay` | 将脱敏 ROS2 消息夹具回放为 Episode | P2 |
| `robot-learning preview-arx ./data/arx-replay` | 校验并列出状态时间轴，不下发动作 | P2 |
| `robot-learning replay --robot arx_x5 --episode ... --execute` | 真机运动回放，硬件安全验收后再实现 | 待定 |
| `robot-learning export SOURCE OUTPUT --format hdf5` | 导出自有 HDF5 布局；不是旧 HDF5 的直接替代 | P3 |
| `robot-learning export SOURCE OUTPUT --format lerobot --repo-id OWNER/NAME --fps 10 --task TASK` | 用外部 LeRobot v3 写入本地数据集 | P3 |
| `robot-learning build-vlm SOURCE OUTPUT --camera base --instruction TEXT` | 按已批准片段构造 ShareGPT 图像数据 | P3 |
| `robot-learning action-stats SOURCE.hdf5` | 汇总 HDF5 动作维度的范围、均值和标准差 | P6 |
| `robot-learning smooth-gripper-hdf5 SOURCE OUTPUT` | 平滑已识别的夹爪字段并写入新 HDF5 文件 | P6 |
| `robot-learning preprocess-video VIDEO SOURCE OUTPUT --camera head_camera` | 均匀抽取 MP4 帧并写入新 HDF5 文件；需 OpenCV | P6 |
| `robot-learning task-demo --port 8766` | 仅本机假语音/VLM/VLA 任务状态页面，无设备执行接口 | P5 |
| `robot-learning deploy --robot arx_x5 --policy pi0 --config ...` | 真机推理与动作发布，真实模型和硬件安全验收后再实现 | P4 后续 |

设备的 ROS1/ROS2 驱动分别在各自进程和环境中启动。CLI 只负责参数校验、接口调用和可读的状态输出；机器人底层控制留在 adapter。`doctor-piper` 和 `doctor-arx` 不连接设备；`collect-piper` 调用旧 SDK `ConnectPort()`，该方法会发送能力查询但不会调用运动控制接口。未发布的 `import-arx-legacy`、`replay-arx-hdf5` 与 `control-web` 用法见[控制与回放](control-and-replay.md)；只有显式 `--publish --limits` 的 HDF5 回放路径会下发 ARX 命令。

配置建议按设备拆文件，字段含义由数据契约约束；正式语法随对应 adapter 发布：

```yaml
robot:
  type: arx_x5
  arm_ids: [left]
  joint_unit: rad
  gripper_unit: TODO_VERIFY
  pose_frame: TODO_VERIFY
camera:
  base:
    topic: /camera_02/color/image_raw
  wrist_left:
    topic: /camera_01/color/image_raw
recording:
  output_root: ${ROBOT_DATA_ROOT}
  sample_rate_hz: 30
  sync_tolerance_ms: TODO_VERIFY
safety:
  require_explicit_execute: true
```

`TODO_VERIFY` 表示必须用设备 SDK 与样本核对的字段，正式配置不能保留占位值。配置文件不写个人主目录、服务器 IP、私有 checkpoint 位置或凭据。路径先使用相对目录和环境变量；命令行可以覆盖非敏感运行参数。输出目录按 `task/episode_id` 组织，每条轨迹保留自己的元数据、图像索引和标注文件。
