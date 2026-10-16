# Piper CAN/ROS1 采集（v0.1.0 预发布）

本版将旧 Piper Qt 脚本中的 CAN 初始化、ROS1 图像订阅、缓冲同步和 Episode 写入拆成独立层。**仅在假 SDK/假 ROS1 下完成离线测试，没有本版真机数据人工核对。**旧项目曾在真机运行不等于重组后已验收。仅限熟悉设备的人员在安全现场尝试；不要用于自动动作执行。

## 离线复现

在仓库根目录安装并运行，无需 ROS、CAN 或 Piper SDK：

```bash
python -m pip install -e .
python examples/collect_piper_synthetic.py ./data/piper-synthetic
robot-learning validate ./data/piper-synthetic
robot-learning inspect ./data/piper-synthetic
robot-learning annotate --data-root ./data
```

示例经相同的 `capture_piper_ros1()` 入口注入假 SDK 与假 ROS1 消息，生成三组状态、主臂动作和双相机帧。输出目录须不存在；在标注页选择 `piper-synthetic` 可以预览其 RGB 图像并保存片段。真实设备依赖**不随仓库安装**。

## 设备环境准备

1. 在已有 ROS1、`rospy` 和 `sensor_msgs` 的环境中安装本包；由设备管理员按厂商要求准备 CAN 接口和相机节点。仓库不提供系统级 ROS/CAN 安装脚本。
2. 将你有权使用的 Piper SDK 模块安装在该 Python 环境中，并确认它提供 `C_PiperInterface_V2(can_name=...)`、`ConnectPort()`、`GetArmJointMsgs()`、`GetArmGripperMsgs()` 及可选控制消息读取方法。默认配置写为 `piper_interface_v2:C_PiperInterface_V2`，仅是外部模块的导入路径，不是随包文件。
3. 复制 `configs/piper_ros1.json`，核对 `can_name`、两个相机 Topic 和容差。`sdk_class` 会在采集进程中导入并执行对应模块，只能使用自己信任的配置与 SDK。`include_action` 默认 `false`；启用前须确认 `GetArmJointCtrl()` / `GetArmGripperCtrl()` 的主臂来源与时间戳。Topic 必须发布未压缩的 `sensor_msgs/Image`。
4. 先执行静态检查，再由现场人员明确运行采集：

```bash
robot-learning doctor-piper --config configs/piper_ros1.json
robot-learning collect-piper --config configs/piper_ros1.json ./data/piper-run-001
robot-learning validate ./data/piper-run-001
```

`doctor-piper` 仅检查 Python 模块和 `/sys/class/net/<can_name>` 是否存在，不连接 CAN、不检查 Topic 是否正在发布。`collect-piper` 初始化 ROS1 订阅、实例化外部 SDK 并调用 `ConnectPort()`；旧 SDK 的该方法会启动 CAN 读线程并发送电机能力、固件查询，**不是零发送 CAN 帧**，但本仓库不调用使能、轨迹或运动控制方法。采集结束后停止该 SDK 的读取循环并取消订阅；外部 SDK 的底层总线资源释放能力尚待设备环境确认。输出目录必须尚不存在，异常退出可能留下部分 Episode，请使用 `validate` 检查。

## 时间与数据约定

- 状态来自 SDK 的关节反馈和夹爪反馈；可选动作来自主臂控制消息，不能将下一个反馈状态冒充命令。数值保持原始 tick，元数据标记 `piper_raw_joint_tick` / `piper_raw_gripper_tick`。
- SDK 关节时间戳按秒转纳秒、夹爪按纳秒读取；ROS1 图像使用 `header.stamp.to_nsec()`。当前假设它们处于同一 epoch/时钟域，尚未用设备证明。不同步时整组丢弃，不自动校正偏移。
- 每相机缓存最多 120 帧，选择与状态时间戳最近且未复用的帧；`sync_tolerance_ms` 和 `camera_wait_ms` 控制容差与等待。重复状态/动作时间戳丢弃，倒退时间戳报错；缺帧不写半组。不插值、不重编码原始图像。
- 只支持未填充行的 `rgb8`、`bgr8`、`mono8`、`mono16`、`16UC1`。压缩图、未知编码或时间戳错误会被拒绝。标注页的片段索引按**图像帧事件**而非采样步计算，多相机标注需特别核对。

## 待补的硬件验收

真实 CAN 连接与关闭、Topic 映射、相机编码、时钟域与掉帧率、关节/夹爪单位、主臂动作来源和一份授权旧录制的数值对照，均**未在 v0.1.0 验证**。这些是 P1 稳定验收条件，不能以 CI 或假设备结果替代。用户提供设备或脱敏样本后，再记录对照结果并修订配置。
