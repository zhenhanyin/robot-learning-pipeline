# Migration map

旧项目：`Data-Collect-and-Deploy-main/`。下表路径均相对旧项目根目录；各行先迁移代表性功能，再以输入、输出和运行行为核对，不批量移动整个旧树。v0.0.2 的同步、Episode 与标注模型是依据需求重新实现的离线基础，不是旧 Piper SDK 或 Web 应用的直接移植。

| 旧位置 | 目标位置 | 迁移任务 | 验收证据 |
| --- | --- | --- | --- |
| `data_collect_piper/songlings/piper_interface_v2.py` | `src/robot_learning/adapters/piper/sdk.py` | 已映射外部 SDK 的只读关节/夹爪消息；CAN 初始化与命令仍待迁 | 假 SDK 回归通过；SDK 许可与真机核对待办 |
| `data_collect_piper/songlings/data_collect.py` | `src/robot_learning/workflows/`、`src/robot_learning/adapters/ros1/` 和 Piper adapter | 已拆开只读编排与 ROS1 原始图像映射；Qt、订阅入口仍待迁 | 合成采集与假 ROS 消息回归通过；真机录制记录待办 |
| `data_collect_piper/songlings/converting_utils.py` | `src/robot_learning/workflows/synchronization.py` | 时间戳同步与片段裁剪 | 包含缺帧、乱序样本的测试 |
| `data_collect_piper/songlings/{utils.py,data_sample_interface/utils.py}` 与 `data_collect.py` 的保存布局 | `src/robot_learning/adapters/piper/legacy.py` | 按旧二进制/PNG 约定只读导入主从关节、夹爪和图像 | 合成旧格式读写、缺帧和坏文件回归；真实旧录制待核对 |
| `data_collect_piper/data_anno/` | `src/robot_learning/annotation/` 与 `src/robot_learning/apps/` | 先以自有标准库实现本机离线标注；不复制旧 FastAPI/Vue 代码 | 用合成轨迹完成标注并重新读取；真机图像预览待核对 |
| `data_collect_piper/*control_web/` 和 `祖传脚本/Deploy/*control_web/` | `apps/control_web/` | 选择一份基线，合并接口 | HTTP→ROS1 映射测试 |
| `data_collect_arx/main/utils/ros_operator.py` | `src/robot_learning/adapters/arx_x5/` | ROS2 图像/机械臂状态适配 | 录制消息回放测试 |
| `data_collect_arx/main/collect_noop.py` | `src/robot_learning/workflows/` | 采集、静止帧过滤与保存 | HDF5 字段对照、真机录制记录 |
| `data_collect_arx/main/{replay.py,set_init.py}` | `src/robot_learning/workflows/replay.py` | 安全起始姿态与回放 | 限位和人工停机验证 |
| `data_collect_arx/inference/` | `src/robot_learning/policies/` | 模型协议和设备发布分离 | 假策略端到端、真机测试 |
| `data_collect_piper/songlings/dataset_to_hdf5&mp4.py` | `src/robot_learning/formats/hdf5.py` | HDF5 导出 | 旧样本读回与维度检查 |
| `祖传脚本/Train/VLA/openpi` | `integrations/openpi/` | 提取数据映射和项目配置 | 小样本加载与模型前处理 |
| `祖传脚本/Train/VLM/LLaMA-Factory` | `integrations/llamafactory/` | 提取 VLM 样本生成脚本和配置 | 图像与文本样本数量校验 |
| `祖传脚本/DataCollection` 和 `祖传脚本/Deploy` | `docs/` | 更新环境与操作说明 | 干净环境按文档复现 |

`data_collect_arx/{ROS,ROS2,py,ARX_VR*,ros2_ws}` 中的上游 SDK、APK、编译产物和 PDF 逐项核对来源。`祖传脚本/Train` 中的上游完整框架不直接进入新仓库。重复的 `copy`、`backup`、`unused` 文件只在能证明确有独立功能时迁移。

## Cross-device decisions before implementation

1. Piper `leader_joint` 与 `follower_joint` 哪个是模型 action 的权威来源；记录控制与反馈的延迟。
2. ARX `joint_action` 当前从从臂 `joint` 生成；确认是否改用真实下发命令或下一状态。
3. ARX、Piper 的关节角、夹爪值、末端坐标单位和相机内外参。
4. 两套设备的时钟源、同步容忍误差和掉帧处理方式。
5. 各模型的输入键名、动作维度与归一化统计量如何随 checkpoint 固定。
