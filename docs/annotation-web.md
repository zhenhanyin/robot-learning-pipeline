# 本机离线标注 Web

`v0.0.4` 提供无需 ROS、CAN 或第三方 Web 框架的片段标注界面。它只处理已存在的 Episode，不采集数据，也不发送机器人指令。

```bash
robot-learning sample ./data/demo
robot-learning annotate --data-root ./data --port 8765
```

在同一台机器的浏览器打开 `http://127.0.0.1:8765/`，选择 Episode、填写标注人，添加或编辑片段后点击“保存标注”。片段范围是帧索引的半开区间 `[开始, 结束)`，结束索引不得超过该 Episode 的帧数。保存时原子替换 `annotation.json`；`metadata.json`、`events.jsonl` 和 `frames/` 不变。命令行 `annotate-span` 仍可用于首次写入单个片段，但不会覆盖已有标注。

服务仅监听 `127.0.0.1`；仅接受本机 Host，同源浏览器请求和 JSON 写入。`--data-root` 必须指向已存在目录，只列出其直接子目录中的 Episode；不能通过 Web 指定任意路径。不要将此服务通过端口转发、反向代理或公网隧道暴露给其他用户，它没有账户认证。停止服务按 `Ctrl+C`。

界面只显示 Episode 元数据和帧数，不预览图像：离线格式允许多种帧编码，当前合成示例为不可直接显示的 `raw8`。与旧项目 FastAPI/Vue 标注页面的图像逐帧对照和真实数据验收，必须等到相机编码和脱敏样本可用后实现；此版本只验证片段标注链路。
