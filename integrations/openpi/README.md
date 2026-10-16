# OpenPI data boundary

`feature-map.example.json` 说明本仓库 LeRobot v3 导出的字段名，不是上游 OpenPI 可直接加载的 `DataConfig`。应先用 `robot-learning export --format lerobot` 导出，并读 `robot_learning_export.json` 核对单位、动作来源、相机名、维度与帧率，再在独立的 OpenPI 环境中编写/配置对应的 `DataConfig`。尤其不能把 `next_state` 标签伪装成真实控制命令。

本仓库不带 OpenPI 源码、权重或归一化统计量，也未对真实模型跑通数据加载。需要现场样本和固定上游版本后，补上模型 reader 的独立集成测试。参考上游 [LeRobot 数据集接口](https://huggingface.co/docs/lerobot/main/api/datasets)。
