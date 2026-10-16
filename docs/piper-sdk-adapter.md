# Piper SDK / ROS1 只读适配

`v0.0.7` 将旧项目的 Piper SDK 消息读取与 ROS1 原始图像解析从 Qt 录制界面拆出。包内不包含 Piper SDK、ROS1 节点启动器或 CAN 驱动；调用方注入已创建的 SDK 对象和 ROS 消息回调。该层不提供 `send_command()`。

```python
from robot_learning.adapters.piper import PiperReadOnlyAdapter
from robot_learning.adapters.ros1 import LatestMessage, Ros1ImageReader

piper_reader = PiperReadOnlyAdapter(existing_sdk, arm_id="left")
base_buffer = LatestMessage()
base_camera = Ros1ImageReader("base", base_buffer.get)
```

在调用方自己的 `rospy.Subscriber` 回调中执行 `base_buffer.update(message)`。`piper_reader.read_state()`、`read_action()` 和 `base_camera.read_frame()` 可注入 `workflows.record_samples()`；它们本身不会写盘或发送命令。

`read_state()` 读取 `GetArmJointMsgs()` / `GetArmGripperMsgs()`；`read_action()` 读取 `GetArmJointCtrl()` / `GetArmGripperCtrl()`，标记为 `LEADER_COMMAND`，不是从臂反馈。关节 SDK 时间戳按秒转纳秒、夹爪 SDK 时间戳按纳秒读取，夹爪与对应关节默认允许 30 ms 偏差。关节/夹爪数值保持旧 SDK 原始 tick，不擅自转换为弧度或长度；创建 Episode 时应把元数据写为 `piper_raw_joint_tick` 和 `piper_raw_gripper_tick`。主从臂 SDK 对象由调用方分别配置，不能混用；真实命令来源、时钟域和单位仍需在设备环境核对。

`Ros1ImageReader` 接受 ROS1 `sensor_msgs/Image` 兼容对象，要求 `header.stamp.to_nsec()`、紧密排列的行、完整 `data`。支持 `rgb8`、`bgr8`、`mono8`、`mono16`、`16UC1`；16 位编码附加 `;endian=little|big`，原始字节不重编码。压缩图、行填充、未知编码和缺失消息会报错。`LatestMessage` 仅缓存最近消息，不实现时间同步或 ROS 订阅；相机 ID 和 Topic 由调用方绑定。

离线假 SDK、假 ROS 消息及 `record_samples()` 组合验证见 `tests/test_piper_sdk.py`。由于当前没有真机，本版未验证 CAN 初始化、ROS Topic、采样频率、时钟对齐、原始 tick 标定和旧录制一致性；可运行采集入口留待后续版本。
