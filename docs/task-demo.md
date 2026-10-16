# Synthetic task dashboard (v0.5.0 pre-release)

旧 `祖传脚本/Deploy/gui_4_2` 文档描述语音、视觉与 VLA 联动，但当前源树缺少其 `lib/` 内部模块。这里不复制 Qt GUI、上游 OpenPI 客户端、硬编码地址、模型权重或 ROS 发布逻辑，而是用自有标准库代码重建**离线协议与任务状态机**。

## Offline replay

```bash
python -m pip install -e .
python examples/task_synthetic.py
robot-learning task-demo --port 8766
```

浏览器仅在本机打开 `http://127.0.0.1:8766/`。输入 `pick sample` 或 `clear table`，依次点击“生成提议”“人工批准”“离线预览”。CLI 示例还通过 `propose_audio()` 用 UTF-8 字节假装语音结果，**不是录音或真实 ASR**。`FakeVision` 只做关键词选择，不是 VLM；`FakePolicy` 只返回固定候选动作，不是 VLA。两个任务分别走 ACT 与 π0.5 形状的策略接口，并由 `OfflinePolicyRunner` 检查合成限位。

`TaskOrchestrator` 依赖 `SpeechRecognizer.transcribe(bytes) -> str`、`VisionPlanner.select_task(str, frames) -> task_id`、观测提供者和明确列出的 `TaskDefinition`。阶段为 `idle → awaiting_approval → approved → completed`；未知任务、过期图像、模型异常使流程进入 `stopped`。批准必须携带当前 `proposal_id`，一次提议只允许一次预览。预览只返回候选数量和 `command_published=false`，不提供 `execute`、ROS 或设备发布路径。要开始新会话，重新创建 orchestrator。

HTTP 仅绑定 `127.0.0.1`，核对 Host/Origin，限制 JSON 请求体和端点；仅有 `/api/status`、`/api/propose`、`/api/approve`、`/api/preview`、`/api/stop`。网页“停止”只锁定演示进程，**不是硬件急停**。HTTP 服务单线程，真实阻塞调用无法被其停止。此版只验证假语音/VLM/VLA 协议和完整合成任务；真实模型、设备动作来源/单位、权限边界及真机演示仍需单独验收。
