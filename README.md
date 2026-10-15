# Robot Learning Pipeline

面向机械臂数据采集、标注、训练数据导出与策略部署的分阶段开源框架。**v0.0.1 仅包含公共数据契约、适配器接口、测试和迁移计划**；ARX X5 与 Piper 的硬件功能尚未迁入，不能用于控制真机。

原始项目 `Data-Collect-and-Deploy-main` 的三个目录会按功能逐项迁移，不会直接复制整棵旧代码树。首版不包含第三方 SDK、权重或真实采集数据。

## 设计目标

- 一套采集、标注和导出流程，分别接入 Piper 与 ARX X5。
- 公共代码不依赖 ROS、CAN、Qt、FastAPI 或特定训练框架。
- 原始观测与训练动作分开记录，明确单位、坐标系、时间戳和动作来源。
- ROS1 与 ROS2 在各自环境运行，使用相同的数据契约。
- CLI 统一常见操作，硬件专属参数留在配置文件中。

## 状态

| 功能 | 状态 | 目标版本 |
| --- | --- | --- |
| 公共数据对象和硬件接口 | 已建立接口 | v0.0.1 |
| Piper 采集、时间同步与标注 | 待迁移 | v0.1.0 |
| ARX X5 ROS2 采集与回放 | 待迁移 | v0.2.0 |
| HDF5、LeRobot 导出与训练配置 | 待迁移 | v0.3.0 |
| 模型推理与真机执行 | 待迁移 | v0.4.0 |
| MagicBot 多模型演示编排 | 待评估 | v0.5.0 |

## 代码组织

```text
src/robot_learning/
  core/                # 数据对象、硬件和模型接口；仅用 Python 标准库
  adapters/            # Piper CAN/ROS1、ARX ROS2 适配器
  workflows/           # 采集、同步、回放等编排
  formats/             # 原始格式、HDF5、LeRobot 转换
  policies/            # 策略客户端与动作后处理
  cli.py               # 未来统一的 robot-learning 命令
apps/
  annotator/           # 标注 Web 前后端
  control_web/         # 远程控制界面
configs/               # 机器人、相机、任务和模型配置示例
integrations/          # OpenPI、LLaMA-Factory 等第三方集成配置
launch/                # ROS1/ROS2 启动文件；各自环境独立
docs/                  # 架构、数据协议、迁移与发布计划
tests/                 # 不依赖真机的契约测试
```

当前仅建立 `core/`；其余目录按发布阶段创建。详见 [架构说明](docs/architecture.md)、[统一命令与配置](docs/cli-and-config.md) 和 [迁移清单](docs/migration.md)。

## 安装与验证

公共核心目标兼容 Python 3.8 及以上版本，不需要连接机械臂：

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -c "from robot_learning.core import ArmState; print(ArmState('left', 0, (0.0,)))"
```

硬件采集命令、依赖安装和真机验证步骤会随对应模块一起发布。当前不提供 `robot-learning collect` 等尚未实现的命令；只需使用 `robot_learning.core` 中的数据对象和接口。

## 版本与发布

`pyproject.toml` 是包版本的唯一来源；发布时创建同号 Git tag，例如 `v0.0.1`。每个版本必须通过测试、文档、许可证和敏感信息检查。完整阶段、验收条件与 GitHub 上传顺序见 [发布计划](docs/release-plan.md)。变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## 开源准备

本仓库自有内容采用 [Apache-2.0 许可证](LICENSE)。ARX SDK、Piper SDK 修改版、Orbbec 驱动、VR APK、OpenPI 与 LLaMA-Factory 等仍需分别确认来源和再分发条件；本许可证不自动覆盖它们。后续迁移先完成 [第三方清单](THIRD_PARTY_NOTICES.md) 与 [发布检查](docs/publish-checklist.md)。

本仓库不接收真实采集数据、模型权重、编译产物、私有地址或密钥。参与开发请读 [CONTRIBUTING.md](CONTRIBUTING.md)；安全相关操作见 [真机使用边界](docs/safety.md)。
