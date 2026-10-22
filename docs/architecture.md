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
                              └─> offline preview (no command publishing)
```

- `core` 只描述跨硬件的数据和接口，不能导入 ROS、CAN、Qt、Web 服务或模型框架。`StateReader` / `ActionReader` 是只读端口，`RobotAdapter` 才有 `send_command()`。
- `adapters` 转换设备原生消息；ROS1 与 ROS2 在不同进程和环境中使用相同契约。
- `workflows` 编排采集、同步、回放；它只依赖 core 接口，不直接解析 CAN 帧。当前 `record_samples()` 仅读取设备，不下发动作。
- 未发布的 `workflows/motion.py` 将限位检查、静止帧判断与可注入的命令发送边界拆开；Piper/ARX 写入适配器分别留在 `adapters/`，不会在普通采集命令中自动启用。
- `formats` 负责原始记录和训练格式转换；标注信息独立保存。
- `formats.training` 先验证并分组 Episode，再分别交给 HDF5、LeRobot 与标注数据导出；LeRobot、NumPy、h5py、Pillow 只在相应导出路径按需加载。
- `policies` 负责加载外部 checkpoint manifest、观测映射/仿射归一化和动作维度校验，输出候选 `RobotCommand`；`workflows.policy_preview` 仍是离线筛选边界。设备使能、真实限位及制造商安全停机仍待真机集成。
- `integrations.http_services` 提供可选 HTTPS 语音、视觉提议和策略推理协议；密钥由环境变量注入，核心模块不依赖或复制供应商 SDK。
- `workflows.task_orchestration` 用 allowlist 和人工批准连接语音、视觉规划与策略预览；Python API 可经显式 `execute()` 调用已注入的设备适配器。内置 `apps.task_demo` 只接合成假实现，不暴露执行接口。
- `apps` 提供 Qt/Web 交互，不承担机械臂协议解析。
- `apps.piper_capture` 是可选的 ROS1/CAN 进程入口；第三方依赖仅在运行时加载，公共 `workflows` 仍只依赖 core 契约。相机回调与数据写入之间由有界 `FrameBuffer` 隔离。
- `apps.arx_capture` 是可选的 ROS2 只读进程入口；`adapters.arx_x5` 只映射消息，不导入 ROS2 驱动。离线 JSONL 消息回放复用同一映射与同步编排，不是运动回放。
- `integrations` 保存外部协议、框架配置和转换脚本，不复制整个上游代码库；第三方依赖只在集成入口按需加载。

## Runtime paths

采集：设备和相机 → 适配器 → 状态/图像 → 时间同步 → EpisodeWriter → 原始数据 → 标注 → 导出。

部署：设备和相机 → 适配器 → 统一观测 → PolicyClient → 动作块 → 限幅与时效检查 → 经人工批准的执行工作流 → RobotAdapter。通用执行 API 与显式 ARX 回放入口已实现；预览默认不发送命令，硬件/急停验收仍未完成。

任务演示：语音/文本 → 视觉白名单提议 → 人工批准 → 模型策略预览；内置示例使用假服务和假策略，外部服务必须显式配置，网页仍无设备执行端点。

训练：标注后的 episode → HDF5/LeRobot/VLM 样本转换 → 上游训练框架 → checkpoint；转换必须记录源 schema 版本。

## Rules for future code

1. 新机器人实现 `RobotAdapter`，声明单位、坐标系和动作来源，提供离线契约测试。
2. 训练字段映射写在 exporter 或集成配置中，不能反向污染原始数据对象。
3. 多臂数据逐臂记录 `arm_id`；只有模型导出时才做 padding 或拼接。`ArmAction` 是数据记录，`RobotCommand` 才可发给设备。
4. 路径、Topic、端口、采样率和相机名由配置注入，不写入通用模块。
5. 每条设备路径提供不接真机即可运行的 fake adapter 测试；真机验证单独记录。
