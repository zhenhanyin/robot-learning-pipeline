# Offline episode v1

`robot-learning sample ./data/demo` 创建一个不连接机械臂的合成 episode。目录必须不存在；重跑前请换目录，避免覆盖原始数据。

```text
data/demo/
  metadata.json       # schema_version、设备名称、时钟域、关节单位
  events.jsonl        # 按写入顺序排列的 state/action/frame 事件
  frames/000000.bin   # 原样二进制帧，不自动压缩或转换
  annotation.json     # 可选，人工标注，与原始事件分离
```

`JsonlEpisodeWriter` 接受 `ArmState`、`ArmAction`、`CameraFrame`；`EpisodeReader.records()` 还原这些对象。每个 JSONL 行有 `type` 和 `data`。帧事件的 `file` 指向 `frames/` 中的二进制文件，编码由 `CameraFrame.encoding` 描述。当前合成示例的 `raw8` 是单字节测试像素，**不是 Piper 相机格式**。`annotation.json` 中片段的索引指向帧序列，`end_index` 不包含在片段内。

`synchronize_timestamps(anchors, streams, tolerance_ns)` 接受严格递增的纳秒时间戳，为每个锚点寻找容差内的最近样本；一条流的样本不会重复使用，缺任意一路时跳过该锚点。输入应属于同一时钟域，时钟偏移需在适配器侧先处理。该函数不插值、不修复乱序，也不自动决定哪一路是权威时钟。

本格式用于离线回归和接口联调。它没有经过真机校准，尚未承诺长时录制性能、崩溃恢复、HDF5 兼容或训练格式导出。迁移 Piper 数据时应先验证时间戳、单位、编码与动作来源，再扩展元数据和转换器。

v0.0.3 可通过 [只读采集编排](collection-workflow.md) 从实现公共读取接口的设备写入同一格式；v0.0.4 可通过 [本机标注 Web](annotation-web.md) 编辑 `annotation.json`。`schema_version` 仍为 1。
