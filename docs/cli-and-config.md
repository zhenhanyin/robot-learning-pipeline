# CLI and configuration design

以下硬件命令仍是目标接口，**v0.0.2 尚未实现它们**。当前可运行的离线命令是 `sample`、`inspect`、`annotate-span`，用法见 README。每个硬件命令只在对应版本完成并经过验证后加入 README 的可运行示例。

| 命令 | 用途 | 最早阶段 |
| --- | --- | --- |
| `robot-learning doctor --robot piper --config configs/robots/piper.yaml` | 只读检查依赖、CAN、ROS Topic、相机与输出目录 | P1 |
| `robot-learning collect --robot piper --task pick-cup --config ...` | 采集一条或多条原始轨迹 | P1 |
| `robot-learning annotate --data-root ./data/raw` | 启动本地标注服务 | P1 |
| `robot-learning doctor --robot arx_x5 --config ...` | 只读检查 ROS2、机械臂与相机 | P2 |
| `robot-learning replay --robot arx_x5 --episode ...` | 默认预览，不下发动作 | P2 |
| `robot-learning replay --robot arx_x5 --episode ... --execute` | 经安全检查后真机回放 | P2 |
| `robot-learning export --input ... --format hdf5` | 导出旧模型使用的 HDF5 | P3 |
| `robot-learning export --input ... --format lerobot` | 导出 OpenPI 使用的 LeRobot 数据 | P3 |
| `robot-learning deploy --robot arx_x5 --policy pi0 --config ...` | 连接模型服务并执行动作 | P4 |

设备的 ROS1/ROS2 驱动分别在各自进程和环境中启动。CLI 只负责参数校验、接口调用和可读的状态输出；机器人底层控制留在 adapter。`doctor` 不会使能或移动机械臂，`replay` 默认不向设备发送命令。

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
