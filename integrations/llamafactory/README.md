# LLaMA-Factory data boundary

`robot-learning build-vlm` 从已人工批准的 Episode 标注生成 `data.json`、`dataset_info.json`、`images/*.png`。`dataset_info.json` 采用 ShareGPT `messages`/`images` 配置及 `role`/`content` 标签；图片相对路径位于输出目录内。将**生成目录**作为训练环境的数据目录，再在其配置中选择数据集 `robot_learning_vlm`。使用与该版本模型匹配的多模态模板，并自行确认图片路径与 `<image>` token 数相同。

参考上游 [LLaMA-Factory 数据说明](https://github.com/hiyouga/LlamaFactory/blob/main/data/README.md)。本仓库不复制其源码、旧项目硬编码的清扫任务或未经人工确认的动作/语言标签。真实训练器加载尚未测试。
