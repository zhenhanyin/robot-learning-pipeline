# 本机离线标注 Web

`v0.0.4` 提供无需 ROS、CAN 或第三方 Web 框架的片段标注界面；`v0.1.0` 加入本机逐帧预览。它只处理已存在的 Episode，不采集数据，也不发送机器人指令。

```bash
robot-learning sample ./data/demo
robot-learning annotate --data-root ./data --port 8765
```

在同一台机器的浏览器打开 `http://127.0.0.1:8765/`，选择 Episode、填写标注人，按图像帧索引预览，再添加或编辑片段并点击“保存标注”。片段范围仍是**帧事件序列**的半开区间 `[开始, 结束)`，结束索引不得超过该 Episode 的图像帧总数；多相机 Episode 的帧索引不是采样步索引，标注前须核对。保存时原子替换 `annotation.json`；`metadata.json`、`events.jsonl` 和 `frames/` 不变。命令行 `annotate-span` 仍可用于首次写入单个片段，但不会覆盖已有标注。

服务仅监听 `127.0.0.1`；仅接受本机 Host，同源浏览器请求和 JSON 写入。`--data-root` 必须指向已存在目录，只列出其直接子目录中的 Episode；不能通过 Web 指定任意路径。不要将此服务通过端口转发、反向代理或公网隧道暴露给其他用户，它没有账户认证。停止服务按 `Ctrl+C`。

预览只支持 PNG、`rgb8`、`bgr8`、`mono8`、合成 `raw8` 与带字节序的 `mono16`/`16UC1`；16 位深度仅显示高字节灰度，不改变原始文件。未知编码、超限尺寸、非法帧引用和符号链接拒绝预览。与旧项目 FastAPI/Vue 标注页面的真实图像对照仍需脱敏样本；当前只做离线回归。
