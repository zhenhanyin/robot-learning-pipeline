# Robot Learning Pipeline

面向机械臂数据采集、标注、训练数据导出与策略部署的分阶段开源框架。**v0.4.0 增加四种策略的注入式推理客户端与离线动作安全预览。** 公共核心仍无需硬件或第三方 SDK。当前仅完成合成轨迹、假模型与注入式接口的离线验证；真实模型加载、真机命令发布和硬件验收尚未完成。

原始项目 `Data-Collect-and-Deploy-main` 的三个目录按功能逐项迁移，不直接复制整棵旧代码树。本仓库不包含第三方 SDK、权重或真实采集数据。

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
| 离线 Episode、同步、标注模型 | 可用，无硬件依赖 | v0.0.2 |
| 只读多源采集编排 | 可用，假设备测试通过 | v0.0.3 |
| 本机离线片段标注 Web | 可用，合成 Episode 测试通过 | v0.0.4 |
| Episode 完整性校验 | 可用，损坏样本回归通过 | v0.0.5 |
| 旧 Piper 录制目录离线导入 | 可用，合成旧格式回归通过；真实旧录制待核对 | v0.0.6 |
| Piper SDK 与 ROS1 Image 只读映射 | 假 SDK/消息回归通过；未连接真机 | v0.0.7 |
| Piper CAN/ROS1 采集、时间同步与标注 | 离线预发布；假设备与合成轨迹通过，真机数据待核对 | v0.1.0 |
| ARX X5 ROS2 采集与回放 | 离线预发布；只读采集与消息夹具回放通过，真机和运动回放未验收 | v0.2.0 |
| HDF5、LeRobot 导出与训练配置 | 离线预发布；HDF5 实际读回、LeRobot 注入式测试通过；模型加载待验收 | v0.3.0 |
| ACT、H-RDT、π0/π0.5 策略与动作控制 | 离线预发布；假模型推理与安全门通过，不下发真机命令 | v0.4.0 |
| MagicBot 多模型演示编排 | 待评估 | v0.5.0 |

## 代码组织

```text
src/robot_learning/
  core/                # 数据对象、只读采集和硬件控制接口；仅用标准库
  adapters/            # Piper CAN/ROS1、ARX ROS2 适配器
  workflows/           # 只读采集、相机帧缓冲与时间戳同步；后续回放编排
  formats/             # JSONL Episode、标注、训练样本组装和可选导出
  annotation/          # 本地 Episode 标注存储与校验
  apps/                # Piper/ARX 采集入口与本机离线标注 Web；后续控制界面
  adapters/piper/       # 旧数据导入、注入式只读 SDK 映射
  adapters/ros1/        # 注入式 ROS1 Image 映射
  adapters/arx_x5/      # 注入式 ROS2 RobotStatus/Image 映射
  policies/            # 策略客户端与显式观测映射
  cli.py               # 离线示例、检查、片段标注和标注 Web 入口
configs/               # 机器人、相机、任务和模型配置示例
integrations/          # OpenPI、LLaMA-Factory 等第三方集成配置
launch/                # ROS1/ROS2 启动文件；各自环境独立
docs/                  # 架构、数据协议、迁移与发布计划
tests/                 # 不依赖真机的契约测试
```

目前实现 `core/`、只读采集与离线策略预览 `workflows/`、离线 `formats/`、Piper 旧数据导入、可选 Piper/ARX 采集入口、本机标注 Web 与可选训练导出；ARX 运动回放和真实模型联调尚未实现。详见 [架构说明](docs/architecture.md)、[ARX ROS2 采集](docs/arx-ros2-collection.md)、[训练数据导出](docs/training-export.md)、[策略离线预览](docs/policy-preview.md) 和 [迁移清单](docs/migration.md)。

## 安装与验证

公共核心目标兼容 Python 3.8 及以上版本，不需要连接机械臂：

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -c "from robot_learning.core import ArmState; print(ArmState('left', 0, (0.0,)))"
robot-learning sample ./data/demo
robot-learning inspect ./data/demo
robot-learning validate ./data/demo
robot-learning annotate-span ./data/demo --annotator demo --start 0 --end 2 --text "pick object"
python examples/collect_synthetic.py ./data/collected-demo
robot-learning inspect ./data/collected-demo
python examples/collect_piper_synthetic.py ./data/piper-synthetic
robot-learning validate ./data/piper-synthetic
python examples/collect_arx_synthetic.py ./data/arx-synthetic
robot-learning validate ./data/arx-synthetic
robot-learning preview-arx ./data/arx-synthetic
robot-learning annotate --data-root ./data
robot-learning import-piper-legacy ./legacy-run ./data/piper-import
robot-learning validate ./data/piper-import
```

训练数据离线示例需要可选依赖；默认只接受明确记录的动作：

```bash
python -m pip install -e '.[hdf5,vlm]'
robot-learning export ./data/collected-demo ./data/collected-demo.hdf5 --format hdf5
robot-learning annotate-span ./data/collected-demo --annotator demo --start 0 --end 4 --text 'pick object' --used-for-vlm
robot-learning build-vlm ./data/collected-demo ./data/vlm-demo --camera base --instruction 'What is happening?'
```

`build-vlm` 前须为 Episode 保存 `used_for_vlm=true` 的片段标注；示例输出目录须不存在，重跑请更换路径。LeRobot 的独立安装、固定帧率和读回步骤见 [训练数据导出](docs/training-export.md)。

策略客户端只以注入式假模型离线验证，下面四条命令均不连接设备：

```bash
python examples/preview_policy_synthetic.py --model act
python examples/preview_policy_synthetic.py --model hrdt
python examples/preview_policy_synthetic.py --model pi0
python examples/preview_policy_synthetic.py --model pi0.5
```

`sample` 生成三帧合成数据；三个 `collect_*synthetic.py` 示例验证通用编排、Piper/ROS1 和 ARX/ROS2 注入路径。`validate` 输出 JSON 检查报告，校验失败时退出码为 1；检查范围见 [校验说明](docs/episode-validation.md)。`import-piper-legacy` 只读取旧目录，目标目录必须不存在；格式假设与未迁字段见 [Piper 旧数据导入](docs/piper-legacy-import.md)。`annotate-span` 使用半开区间 `[start,end)`，标注文件独立于原始事件。`annotate` 仅绑定 `127.0.0.1`，浏览器打开 `http://127.0.0.1:8765/`；支持部分编码逐帧预览，详细限制见 [本机标注说明](docs/annotation-web.md)。输出格式见 [离线格式说明](docs/offline-episode.md)。真实环境的可选命令与依赖见 [Piper ROS1 采集](docs/piper-ros1-collection.md) 和 [ARX ROS2 采集](docs/arx-ros2-collection.md)；当前没有通用 `robot-learning collect` 或已验收的真机采集流程。

## 版本与发布

`pyproject.toml` 是包版本的唯一来源；发布时创建同号 Git tag，例如 `v0.0.1`。每个版本必须通过测试、文档、许可证和敏感信息检查。完整阶段、验收条件与 GitHub 上传顺序见 [发布计划](docs/release-plan.md)。变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## 开源准备

本仓库自有内容采用 [Apache-2.0 许可证](LICENSE)。ARX SDK、Piper SDK 修改版、Orbbec 驱动、VR APK、OpenPI 与 LLaMA-Factory 等仍需分别确认来源和再分发条件；本许可证不自动覆盖它们。后续迁移先完成 [第三方清单](THIRD_PARTY_NOTICES.md) 与 [发布检查](docs/publish-checklist.md)。

本仓库不接收真实采集数据、模型权重、编译产物、私有地址或密钥。参与开发请读 [CONTRIBUTING.md](CONTRIBUTING.md)；安全相关操作见 [真机使用边界](docs/safety.md)。
