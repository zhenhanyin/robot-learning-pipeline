# Piper 旧录制目录导入

`v0.0.6` 将旧 `data_collect_piper/songlings/data_collect.py` 生成的一条运行目录只读转换为新的 JSONL Episode。原目录不会改写或删除；目标目录必须不存在。

```bash
robot-learning import-piper-legacy ./legacy-run ./data/piper-import --tolerance-ms 30
robot-learning validate ./data/piper-import
robot-learning inspect ./data/piper-import
```

要求旧目录包含 `follower_joint`、`follower_gripper`、`leader_joint`、`leader_gripper` 和 `img/{front_color,wrist_color}/`。可选 `img/{front_depth,wrist_depth}/` 必须成对出现且两者都有图像。二进制关节记录按 `>ddiiiiii`、夹爪记录按 `>ddiii` 解析；不导入旧 SDK。前置图像的 PNG 时间戳作为同步锚点，其他流按容差寻找最近且不复用的样本，缺任一路则丢弃该锚点。

| 旧字段 | 新记录 | 说明 |
| --- | --- | --- |
| `follower_joint` + `follower_gripper` | `ArmState` | 关节时间戳保留；夹爪取对应最近样本 |
| `leader_joint` + `leader_gripper` | `ArmAction(LEADER_COMMAND)` | 主臂命令，不当作从臂反馈 |
| `front_color`、`wrist_color` | `CameraFrame(base/wrist_left)` | 原始 PNG 字节不重编码 |
| `front_depth`、`wrist_depth` | `CameraFrame(base_depth/wrist_left_depth)` | 成对存在时一并导入 |

旧关节、夹爪整数保留为 float 数值，元数据分别标为 `piper_raw_joint_tick` 和 `piper_raw_gripper_tick`；没有假设校准后的弧度/毫米。旧 joint 记录和 PNG 名称按秒解释，旧 gripper 记录按纳秒解释；时钟域只标记为 `legacy_piper_epoch_assumed`，**尚未用真实录制核对**。PNG 只检查文件头与尺寸，不进行完整解码。

目前未映射 `follower_endpose`、旧 `ano.json` 和旧任务状态；源目录仍保留这些数据。旧标注的索引按同步后的时间步，而新标注索引按逐相机帧事件，不能直接复制。该导入器是迁移的一步，不代表 Piper 实时 CAN/ROS1 适配器、真机同步或训练动作语义已经验收。建议先在一份经授权的旧录制上对比帧数、时间戳、单位和动作来源，再用于训练。
