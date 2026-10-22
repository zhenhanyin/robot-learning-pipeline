# Migration map

旧项目：`Data-Collect-and-Deploy-main/`。下表路径均相对旧项目根目录；各行先迁移代表性功能，再以输入、输出和运行行为核对，不批量移动整个旧树。v0.0.2 的同步、Episode 与标注模型是依据需求重新实现的离线基础，不是旧 Piper SDK 或 Web 应用的直接移植。

| 旧位置 | 目标位置 | 迁移任务 | 验收证据 |
| --- | --- | --- | --- |
| `data_collect_piper/songlings/piper_interface_v2.py` | `src/robot_learning/adapters/piper/{sdk,command}.py` | 已映射外部 SDK 的只读消息和显式开启的关节/夹爪命令；仍依赖用户安装的 SDK | 假 SDK 读写测试；SDK 许可与真机核对待办 |
| `data_collect_piper/songlings/data_collect.py` | `src/robot_learning/workflows/`、`src/robot_learning/adapters/ros1/`、`src/robot_learning/apps/piper_capture.py` | 已拆出只读编排、缓冲同步、ROS1 订阅与 CAN 初始化入口；旧 Qt 界面不复制 | 假 SDK/ROS1 录制及校验通过；真机录制记录待办 |
| `data_collect_piper/songlings/converting_utils.py` | `src/robot_learning/workflows/synchronization.py` | 时间戳同步与片段裁剪 | 包含缺帧、乱序样本的测试 |
| `data_collect_piper/songlings/{utils.py,data_sample_interface/utils.py}` 与 `data_collect.py` 的保存布局 | `src/robot_learning/adapters/piper/legacy.py` | 按旧二进制/PNG 约定只读导入主从关节、夹爪、对齐后的末端姿态、RGB 与可选深度图 | 合成旧格式与深度位宽回归；真实单位仍待核对 |
| `data_collect_piper/data_anno/` | `src/robot_learning/annotation/` 与 `src/robot_learning/apps/` | 自有标准库本机离线标注与受限逐帧预览；不复制旧 FastAPI/Vue 代码 | 合成轨迹标注和 PNG/原始帧预览通过；真实图像对照待办 |
| `data_collect_piper/*control_web/` 和 `祖传脚本/Deploy/*control_web/` | `src/robot_learning/apps/control_web.py` | 已按旧服务名和 Topic 重写回环 HTTP→ROS1 映射；不复制旧页面/跨域设置 | 假 ROS 服务、消息映射测试；实际 ROS1 待核对 |
| `祖传脚本/Deploy/gui_4_2/{main.py,main.qml}` 与 `DeploySystem.md` | `src/robot_learning/workflows/task_orchestration.py`、`src/robot_learning/apps/task_demo.py` | 根据旧文档的语音→视觉→VLA 和停止/返回交互，重写白名单提议、人工批准与仅本机合成预览；旧 `lib/` 在当前源树缺失，不能声称完整移植 | 两个假任务、注入式语音/VLM/VLA、HTTP 状态与拒绝路径回归；真实模型和设备链路待办 |
| `data_collect_arx/main/utils/ros_operator.py` | `src/robot_learning/adapters/arx_x5/`、`src/robot_learning/apps/arx_capture.py` | 已迁只读从臂状态、彩色图像、ROS2 订阅与离线消息夹具回放；另有显式命令适配器 | 合成消息、假 ROS2 与命令映射测试；单位和真机待核对 |
| `data_collect_arx/main/collect_noop.py` | `src/robot_learning/adapters/arx_x5/legacy.py`、`src/robot_learning/workflows/motion.py`、`src/robot_learning/apps/arx_capture.py` | 旧 HDF5 左臂关节/夹爪、末端姿态、JPEG 与逐帧相机标定导入；空点云记录来源形状，非空点云在格式确认前拒绝 | 旧 `episode0.hdf5` 离线导入、校验和训练导出通过；单位与动作语义仍待确认 |
| `data_collect_arx/main/{replay.py,set_init.py}` | `src/robot_learning/apps/arx_replay.py`、`src/robot_learning/adapters/arx_x5/command.py` | 已重写旧 HDF5→`RobotCmd` 显式发布和从当前状态插值；默认只预览，限位配置由使用者提供 | 假发布与越界拒绝测试；真机停机/限位验收待办 |
| `data_collect_arx/inference/{act_infer.py,hrdt_infer.py,pi0_infer.py,utils/client.py}` | `src/robot_learning/policies/{client,factory}.py`、`src/robot_learning/workflows/{policy_preview,motion}.py` | 已拆出 ACT/H-RDT/π0/π0.5 调用形状、外部组件加载、显式相机映射和命令边界；不复制旧 pickle 协议或上游权重 | 假模型与拒绝路径回归；checkpoint 专属预处理和真机测试待办 |
| `data_collect_piper/songlings/dataset_to_hdf5&mp4.py` 与 ARX `collect_noop.py` 保存逻辑 | `src/robot_learning/formats/{training,hdf5}.py` | 已重写严格训练样本组装与自有 HDF5 布局；保存末端姿态、深度模态和相机标定，不导入右臂填零作为真实状态 | 合成与旧 ARX 样本 HDF5 读回通过；真实单位待核对 |
| ARX `main/{process_gripper.py,calc_stat.py,replay_smooth.py}` 与 Piper `video_preprocess.py` | `src/robot_learning/formats/{preprocessing,video}.py` | 新建动作统计、归一化 API、夹爪平滑副本与均匀抽帧视频写入 | 合成 HDF5 回归；真实 OpenCV 视频解码待验证 |
| `祖传脚本/Train/VLA/openpi` | `src/robot_learning/formats/lerobot.py`、`integrations/openpi/` | 可选 LeRobot v3 公共 API 适配与字段映射示例，不复制上游 | 假 LeRobot 写入/读回通过；真实包及 OpenPI 加载待办 |
| `祖传脚本/Train/VLM/LLaMA-Factory` | `src/robot_learning/formats/vlm.py`、`integrations/llamafactory/` | 按已批准片段生成 ShareGPT 图像数据与 dataset_info，不迁硬编码标签 | 合成图像、文本与配置回归通过；模型加载待办 |
| `祖传脚本/DataCollection` 和 `祖传脚本/Deploy` | `docs/` | 更新环境与操作说明 | 干净环境按文档复现 |

`data_collect_arx/{ROS,ROS2,py,ARX_VR*,ros2_ws}` 中的上游 SDK、APK、编译产物和 PDF 逐项核对来源。`祖传脚本/Train` 中的上游完整框架不直接进入新仓库。`祖传脚本/Algo` 和 `Preliminary` 当前仅见文档与图片，仍需逐文档核对需不需要保留。重复的 `copy`、`backup`、`unused` 文件只在能证明确有独立功能时迁移。P6 迁移内容归入 `v0.6.0`，不回写到已发布的 `v0.5.0`。

## Cross-device decisions before implementation

1. Piper `leader_joint` 与 `follower_joint` 哪个是模型 action 的权威来源；记录控制与反馈的延迟。
2. ARX `joint_action` 当前从从臂 `joint` 生成；确认是否改用真实下发命令或下一状态。
3. ARX、Piper 的关节角、夹爪值、末端坐标单位和相机内外参。
4. 两套设备的时钟源、同步容忍误差和掉帧处理方式。
5. 各模型的输入键名、动作维度与归一化统计量如何随 checkpoint 固定。
