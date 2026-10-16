# Architecture

## Module boundaries

```text
Piper CAN/ROS1 ─┐
                ├─ adapters ──> core contracts ──> workflows ──> formats
ARX X5 ROS2 ───┘                       │                  │
                                     │                  └─> annotation app
Camera adapters ───────────────────────┘

                           policies <── model servers <── training integrations
                              │
                              └─> robot adapter.send_command()
```

- `core` 只描述跨硬件的数据和接口，不能导入 ROS、CAN、Qt、Web 服务或模型框架。`StateReader` / `ActionReader` 是只读端口，`RobotAdapter` 才有 `send_command()`。
- `adapters` 转换设备原生消息；ROS1 与 ROS2 在不同进程和环境中使用相同契约。
- `workflows` 编排采集、同步、回放；它只依赖 core 接口，不直接解析 CAN 帧。当前 `record_samples()` 仅读取设备，不下发动作。
- `formats` 负责原始记录和训练格式转换；标注信息独立保存。
- `policies` 负责模型协议和动作后处理，输出 `RobotCommand`；设备使能及关节限制留给适配器和运行配置。
- `apps` 提供 Qt/Web 交互，不承担机械臂协议解析。
- `apps.piper_capture` 是可选的 ROS1/CAN 进程入口；第三方依赖仅在运行时加载，公共 `workflows` 仍只依赖 core 契约。相机回调与数据写入之间由有界 `FrameBuffer` 隔离。
- `integrations` 保存第三方框架的配置、转换脚本和补丁，不复制整个上游代码库。

## Runtime paths

采集：设备和相机 → 适配器 → 状态/图像 → 时间同步 → EpisodeWriter → 原始数据 → 标注 → 导出。

部署：设备和相机 → 适配器 → 统一观测 → PolicyClient → 动作块 → 限幅与启停检查 → RobotAdapter。

训练：标注后的 episode → HDF5/LeRobot/VLM 样本转换 → 上游训练框架 → checkpoint；转换必须记录源 schema 版本。

## Rules for future code

1. 新机器人实现 `RobotAdapter`，声明单位、坐标系和动作来源，提供离线契约测试。
2. 训练字段映射写在 exporter 或集成配置中，不能反向污染原始数据对象。
3. 多臂数据逐臂记录 `arm_id`；只有模型导出时才做 padding 或拼接。`ArmAction` 是数据记录，`RobotCommand` 才可发给设备。
4. 路径、Topic、端口、采样率和相机名由配置注入，不写入通用模块。
5. 每条设备路径提供不接真机即可运行的 fake adapter 测试；真机验证单独记录。
