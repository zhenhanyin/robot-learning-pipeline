# Real-robot operation boundary

P0 只定义数据对象和接口，不连接设备。后续启用真机动作前，适配器必须检查设备型号、关节维度、单位、坐标系、动作范围、控制模式与执行权限。启动时保持主从臂安全姿态；回放和策略动作先通过离线记录及限位检查，再由熟悉设备的人员现场验证。

`record_samples()` 与 `record_buffered_samples()` 只写观测，不调用 `send_command()`。`collect-piper` 会调用外部 SDK 的 `ConnectPort()`：旧 SDK 实现会启动 CAN 读取线程并发送能力/固件查询，不应被描述为“完全不发送 CAN 帧”；本仓库不会调用运动控制接口。使用前仍须核对实际 SDK 版本、CAN 接口、急停与现场安全流程；本版没有真机验证或 ARX 驱动。

`collect-arx` 仅订阅从臂 `RobotStatus` 和相机 `Image`，不创建命令发布器。`replay-arx-messages` 只把脱敏 ROS2 形状的消息夹具写成 Episode；`preview-arx` 只读 Episode。旧 `replay.py` 曾发布 `RobotCmd`，但当前版本没有迁移这条控制路径，也不提供 `--execute`。ARX 单位、起始姿态、限位、急停、控制模式和真实 Topic 均未验收；不能将离线测试当成真机安全批准。

推理超时、模型断线、观测过期、相机掉帧或动作维度不符时，应停止下发动作并将设备切换到制造商推荐的安全状态。远程 Web 控制需要身份验证和网络边界，不可公开暴露设备控制接口。
