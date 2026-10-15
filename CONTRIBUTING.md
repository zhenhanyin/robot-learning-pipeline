# Contributing

欢迎参与 Piper、ARX X5、数据格式和训练部署集成。首次提交前请读 [架构说明](docs/architecture.md)、[数据契约](docs/data-contract.md) 和 [真机使用边界](docs/safety.md)。

## 开发方式

1. 从 `main` 创建一个短期功能分支，一个 PR 只迁移一个可验证的功能。
2. 在 PR 中写明旧代码出处、设备环境、输入输出字段、单位、运行步骤和测试证据。
3. 硬件接口保持在 `adapters/`；通用采集与转换逻辑放在 `workflows/` 或 `formats/`。
4. 不提交真实采集数据、权重、构建产物、私有地址、密钥或许可证不明的上游代码。
5. 运行公共核心测试：`PYTHONPATH=src python -m unittest discover -s tests -v`。
6. 真机动作变更先使用假设备或录制数据验证，并在 PR 中提供限位、急停和异常停止结果。

版本号由维护者在发布 PR 中统一更新。用户可见变化记录到 `CHANGELOG.md`；改变 episode 格式时同时写转换说明和 schema 版本。完整发布门槛见 [分阶段发布计划](docs/release-plan.md)。
