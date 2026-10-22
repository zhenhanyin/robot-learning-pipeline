# Third-party inventory

公开前逐项核对来源、版本、许可证、修改内容和再分发条件。仅看到子目录有许可证文件，不能推断整个旧项目可以使用同一种许可证。

| 来源 | 旧项目位置 | 计划处理 | 发布前状态 |
| --- | --- | --- | --- |
| ARX X5 SDK、ROS/ROS2、VR 软件和 PDF | `data_collect_arx/{ROS,ROS2,py,ARX_VR,ARX_VR_SDK,00-readme}` | 优先引用上游；只迁移允许再分发的自有适配代码 | 待核对 |
| Orbbec ROS2 驱动与 SDK | `data_collect_arx/ros2_ws/src/OrbbecSDK_ROS2` | 上游依赖固定版本，不复制编译产物 | 待核对 |
| OpenCV 视频解码 | 新仓库可选 `video` 依赖 | 仅由使用者环境安装，用于 MP4 抽帧；不复制源码 | 上游包许可随依赖安装审查 |
| 修改版 Piper CAN SDK | `data_collect_piper/songlings/piper_interface_v2.py` | 对照上游许可和修改点，决定依赖、fork 或补丁 | 待核对 |
| `ros_numpy` 副本 | `data_collect_piper/songlings/ros_numpy` | 优先改为依赖，核对许可 | 待核对 |
| OpenPI | `祖传脚本/Train/VLA/openpi` | 仅保留项目特有配置和补丁；依赖或 fork 上游 | 待核对 |
| LLaMA-Factory | `祖传脚本/Train/VLM/LLaMA-Factory` | 仅保留数据构造、配置；依赖或 fork 上游 | 待核对 |
| VR APK、预编译 `.so`、模型权重 | 多处 | 默认不进入公开仓库，确需发布时单独审查 | 待核对 |

截至 v0.8.0，本仓库不包含上表中的第三方代码、二进制文件、APK、模型权重或生成工作空间。Piper/ROS1、ARX/ROS2 与 VR 入口由用户环境提供 SDK/ROS 消息/IK；采集操作台只启动配置列出的采集 CLI。HDF5、LeRobot、VLM 与视频导出按需使用 NumPy、h5py、Pillow、LeRobot、OpenCV；外部语音/VLM/VLA 由标准库 HTTPS 客户端接入。ACT、H-RDT、OpenPI、GR00T、LLaMA-Factory、Whisper、CosyVoice、YOLO 均不随包分发。每个后续保留的第三方组件仍需记录上游 URL、版本、许可证、修改内容、归属声明和分发方式。根目录 `LICENSE` 仅覆盖本仓库自有内容。
