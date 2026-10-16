# Offline policy preview (v0.4.0 pre-release)

P4 将旧 ARX 推理脚本里的模型调用、相机命名和动作校验拆开；不复制旧脚本内的固定姿态、硬编码文件路径、pickle socket 服务或 ROS 命令发布。`ModelPolicyClient` 接受外部注入的 ACT `get_chunk`、H-RDT `predict_action` 或 π0/π0.5 `infer` 对象，不安装、不加载模型。`PolicySpec` 必须指定模型名、逐路相机映射、单臂关节维度、可选夹爪是否占动作末尾及 OpenPI 提示词。

`encode_frame` 由集成者注入，将 `CameraFrame` 转成对应 checkpoint 所需张量或图像。本仓库的合成示例只返回原始字节，不代表可直接喂给 ACT/H-RDT/OpenPI。模型的归一化统计、关节顺序、相机颜色空间、采样频率和动作单位都须随 checkpoint 单独确认；不隐式补零、裁剪 14 维或改写夹爪值。

```bash
python examples/preview_policy_synthetic.py --model act
python examples/preview_policy_synthetic.py --model hrdt
python examples/preview_policy_synthetic.py --model pi0
python examples/preview_policy_synthetic.py --model pi0.5
python -m unittest discover -s tests -p 'test_policy_preview.py' -v
```

`OfflinePolicyRunner.preview(state, frames, now_ns)` 只返回候选 `RobotCommand` 元组，**不发布命令**。调用者提供与 `state.timestamp_ns` 相同时间基的 `now_ns`；`SafetyEnvelope` 必须显式指定关节上下限、逐步最大变化量、观测年龄、相机时差和推理耗时限值。策略动作块默认最多 64 步，可用 `PolicySpec.max_chunk_steps` 调整。任何缺失相机、异常/非有限模型输出、超限、断线或主动 `emergency_stop()` 都会锁定 runner。动作块中每一步和前一步比较，不允许越界值自动截断。

耗时使用单调时钟在同步调用返回后核对，**不是硬超时**：阻塞的模型调用不会被它中断；设备硬急停、驱动停机及权限控制尚不存在。即使候选动作通过此检查，也不能连接真机。当前测试只覆盖假模型和合成单臂数据，不是 P4 的真实模型或硬件验收。需要真实部署时应另建进程隔离/看门狗及设备负责人审批，并记录真机演示。
