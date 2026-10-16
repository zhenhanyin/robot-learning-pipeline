# Read-only collection workflow

v0.0.3 的 `record_samples()` 将旧 Piper 采集脚本中混合的读取、对齐和落盘职责拆开：设备只需实现标准库 `core.ports` 的读取接口，编排层不导入 CAN、ROS、Qt 或相机 SDK，JSONL 写入由 `formats` 负责。本版没有复制旧 SDK 或真机控制代码。

```python
from pathlib import Path

from robot_learning.formats import JsonlEpisodeWriter
from robot_learning.workflows import record_samples

with JsonlEpisodeWriter(Path("data/run-001"), "piper", "device_clock", "rad") as writer:
    summary = record_samples(
        state_reader,
        {"base": base_camera, "wrist_left": wrist_camera},
        writer,
        attempts=100,
        tolerance_ns=5_000_000,
        action_reader=leader_action_reader,
    )
```

上例中的 `state_reader`、相机和 `leader_action_reader` 是注入对象。v0.1.0 已提供 Piper SDK/ROS1 可选采集入口，但本例仍展示硬件无关的通用写法。动作读取器可省略；只有明确取得并标注来源的动作才写入 `ArmAction`。`record_samples()` 从不发送 `RobotCommand`，也不会自动把下一状态伪装成设备命令。

可运行的假设备实现见 `examples/collect_synthetic.py`：安装包后执行 `python examples/collect_synthetic.py ./data/collected-demo`，再用 `robot-learning inspect ./data/collected-demo` 检查。示例产生的 `LEADER_COMMAND` 仅为合成动作，不代表真实 Piper 主臂数据。

每次尝试依次读取一个机械臂状态、各相机帧和可选动作。所有记录的纳秒时间戳必须来自同一时钟域；超过与状态时间戳的容差时丢弃**整组**，不写入半组。来源时间戳必须严格递增，机械臂和相机标识必须一致，否则报错。`CollectionSummary` 报告尝试、写入和丢弃数量。写入器由调用方关闭，输出目录必须尚不存在。写盘异常时可能留下部分事件，本版不提供崩溃恢复。

此流程是无缓存的同步轮询，不能处理 ROS 回调队列、时钟偏移、插值或高吞吐视频。Piper 入口改用 `FrameBuffer` 和 `record_buffered_samples()`：每相机缓存有序帧，按机械臂状态时间戳取最近且未复用的图像，超容差或缺失时丢弃整组；重复状态时间戳也丢弃。它不做时钟域转换或插值，详见 [Piper ROS1 采集](piper-ros1-collection.md)。目前仍只支持单臂 Episode；真机接入前必须完成设备时间戳、单位、动作来源与采样速率核对。离线已有时间序列的匹配仍可直接使用 `synchronize_timestamps()`。
