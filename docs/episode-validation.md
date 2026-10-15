# Episode 完整性检查

导出训练数据前，先对每条离线 Episode 运行：

```bash
robot-learning validate ./data/demo
```

命令输出 `valid`、按类型统计的 `counts` 和 `errors`，成功退出码为 0，发现错误退出码为 1。Python API 为 `robot_learning.formats.validate_episode(path)`，不修改 Episode。

检查包括：schema 版本与必需元数据；JSONL 事件结构、逐类型逐设备流递增的纳秒时间戳；帧文件是否缺失、为空、重复引用、未被引用或指向符号链接；记录能否由 `EpisodeReader` 读回；可选标注片段是否落在帧数范围内。若文件结构或内容已损坏，报告会列出可定位的错误，计数仍表示识别到的事件类型数量，**不等于有效样本数量**。

此检查不验证图像编码是否能解码，也不验证真实设备单位、相机标定、时钟域对齐或动作语义。它不能代替真机验收；未经核对的 Piper/ARX 数据不要直接用于模型训练或真机部署。
