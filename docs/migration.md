# Migration map

旧项目：`Data-Collect-and-Deploy-main/`。下表路径均相对旧项目根目录；各行先迁移代表性功能，再以输入、输出和运行行为核对，不批量移动整个旧树。v0.0.2 的同步、Episode 与标注模型是依据需求重新实现的离线基础，不是旧 Piper SDK 或 Web 应用的直接移植。

| 旧位置 | 目标位置 | 迁移任务 | 验收证据 |
| --- | --- | --- | --- |
| `data_collect_piper/songlings/piper_interface_v2.py` | `src/robot_learning/adapters/piper/sdk.py` | 已映射外部 SDK 的只读关节/夹爪消息；CAN 初始化与命令仍待迁 | 假 SDK 回归通过；SDK 许可与真机核对待办 |
| `data_collect_piper/songlings/data_collect.py` | `src/robot_learning/workflows/`、`src/robot_learning/adapters/ros1/`、`src/robot_learning/apps/piper_capture.py` | 已拆出只读编排、缓冲同步、ROS1 订阅与 CAN 初始化入口；旧 Qt 界面不复制 | 假 SDK/ROS1 录制及校验通过；真机录制记录待办 |
| `data_collect_piper/songlings/converting_utils.py` | `src/robot_learning/workflows/synchronization.py` | 时间戳同步与片段裁剪 | 包含缺帧、乱序样本的测试 |
| `data_collect_piper/songlings/{utils.py,data_sample_interface/utils.py}` 与 `data_collect.py` 的保存布局 | `src/robot_learning/adapters/piper/legacy.py` | 按旧二进制/PNG 约定只读导入主从关节、夹爪和图像 | 合成旧格式读写、缺帧和坏文件回归；真实旧录制待核对 |
| `data_collect_piper/data_anno/` | `src/robot_learning/annotation/` 与 `src/robot_learning/apps/` | 自有标准库本机离线标注与受限逐帧预览；不复制旧 FastAPI/Vue 代码 | 合成轨迹标注和 PNG/原始帧预览通过；真实图像对照待办 |
| `data_collect_piper/*control_web/` 和 `祖传脚本/Deploy/*control_web/` | `apps/control_web/` | 选择一份基线，合并接口 | HTTP→ROS1 映射测试 |
| `data_collect_arx/main/utils/ros_operator.py` | `src/robot_learning/adapters/arx_x5/`、`src/robot_learning/apps/arx_capture.py` | 已迁只读从臂状态、彩色图像、ROS2 订阅与离线消息夹具回放；不迁命令发布 | 合成消息与假 ROS2 测试通过；真实录制和单位待核对 |
| `data_collect_arx/main/collect_noop.py` | `src/robot_learning/workflows/` | 采集、静止帧过滤与保存 | HDF5 字段对照、真机录制记录 |
| `data_collect_arx/main/{replay.py,set_init.py}` | 待定的安全控制模块 | 旧 HDF5→`RobotCmd` 真机运动回放未迁；本版只提供不下发动作的离线预览 | 限位、单位、急停和人工停机验证待办 |
| `data_collect_arx/inference/{act_infer.py,hrdt_infer.py,pi0_infer.py,utils/client.py}` | `src/robot_learning/policies/client.py`、`src/robot_learning/workflows/policy_preview.py` | 已拆出 ACT/H-RDT/π0/π0.5 模型调用形状、显式相机映射及离线安全门；不复制 pickle 网络协议、上游权重、固定姿态或 ROS 发布逻辑 | 四种假模型、迟到结果、断线与急停回归；真实模型与真机测试待办 |
| `data_collect_piper/songlings/dataset_to_hdf5&mp4.py` 与 ARX `collect_noop.py` 保存逻辑 | `src/robot_learning/formats/{training,hdf5}.py` | 已重写严格训练样本组装与自有 HDF5 布局；旧 JPEG/左右臂填零格式未照搬 | 合成数据 HDF5 读回通过；真实旧样本字段对照待办 |
| `祖传脚本/Train/VLA/openpi` | `src/robot_learning/formats/lerobot.py`、`integrations/openpi/` | 可选 LeRobot v3 公共 API 适配与字段映射示例，不复制上游 | 假 LeRobot 写入/读回通过；真实包及 OpenPI 加载待办 |
| `祖传脚本/Train/VLM/LLaMA-Factory` | `src/robot_learning/formats/vlm.py`、`integrations/llamafactory/` | 按已批准片段生成 ShareGPT 图像数据与 dataset_info，不迁硬编码标签 | 合成图像、文本与配置回归通过；模型加载待办 |
| `祖传脚本/DataCollection` 和 `祖传脚本/Deploy` | `docs/` | 更新环境与操作说明 | 干净环境按文档复现 |

`data_collect_arx/{ROS,ROS2,py,ARX_VR*,ros2_ws}` 中的上游 SDK、APK、编译产物和 PDF 逐项核对来源。`祖传脚本/Train` 中的上游完整框架不直接进入新仓库。重复的 `copy`、`backup`、`unused` 文件只在能证明确有独立功能时迁移。

## Cross-device decisions before implementation

1. Piper `leader_joint` 与 `follower_joint` 哪个是模型 action 的权威来源；记录控制与反馈的延迟。
2. ARX `joint_action` 当前从从臂 `joint` 生成；确认是否改用真实下发命令或下一状态。
3. ARX、Piper 的关节角、夹爪值、末端坐标单位和相机内外参。
4. 两套设备的时钟源、同步容忍误差和掉帧处理方式。
5. 各模型的输入键名、动作维度与归一化统计量如何随 checkpoint 固定。
