# Training data export (v0.3.0 pre-release)

P3 把 Episode 转成两个互不依赖的训练目标：自有 HDF5 布局，以及通过外部 LeRobot v3 公共 API 生成的本地数据集。`src/robot_learning/formats/training.py` 是唯一的观测组装入口：先跑 Episode 完整性校验，再逐状态关联**一条**同臂动作及每路相机帧。缺动作、缺相机、维度变化、不同动作来源、非有限数值或超容差时间戳直接报错，不补零、不默默丢帧。

默认只接受 Episode 中真正记录的 `ArmAction`。ARX v0.2.0 只有从臂反馈，没有权威控制动作；如仅做下一状态预测试验，必须显式指定 `--action-policy next-state`，以后一状态作为当前训练目标并舍弃最后一帧。导出标记来源 `next_state`，**不能将其当作已经下发的控制指令**。Piper 旧整数 tick 和 ARX 未确认的单位也只原样保留，导出不替用户假定弧度、毫米或归一化范围。

## HDF5

在安装 `numpy`/`h5py` 的环境中运行：

```bash
python -m pip install -e '.[hdf5]'
robot-learning export ./data/demo ./data/demo.hdf5 --format hdf5
```

文件包含属性 `schema_version`、`robot_model`、`clock_domain`、`joint_units`、可选 `gripper_units`、`arm_id` 和 `action_source`。数据集包括关节状态/动作、可选夹爪与末端姿态，以及 `observation/images/<camera>` 下的原始图像、编码、RGB/深度模态和逐帧相机标定。原始字节不重压缩；没有的字段不会补造。这是 **robot_learning_hdf5_v1** 布局，**不是**旧脚本 `joint_action/left_arm` / JPEG `observation/*/rgb` 的直接替代品；旧 HDF5 训练器需另做字段映射并核对实际样本。

## LeRobot v3 / OpenPI

在独立且兼容的 Python 环境安装 `lerobot>=0.4.0` 后：

```bash
python -m pip install -e '.[lerobot]'
robot-learning export ./data/demo ./data/demo-lerobot --format lerobot \
  --repo-id local/demo --fps 10 --task 'synthetic pick'
```

调用外部 `LeRobotDataset.create/add_frame/save_episode/finalize`，使用 `observation.state`、`action`、RGB 图像和逐帧 `task`。深度相机从 LeRobot 图像特征中排除，并在导出清单保留模态、相机标定和末端姿态格式。本地采用 `use_videos=False` 的图像存储，不上传 Hub。导出后用相同类重新读回首样本；`robot_learning_export.json` 保存源时间戳、单位与动作来源。LeRobot 会按固定 `fps` 重建内部时间；源状态时间间隔偏离指定帧率超过 20% 时拒绝导出。特征映射示例见 [OpenPI 集成](../integrations/openpi/README.md)。

当前 CI 没有安装 LeRobot/OpenPI、Torch 或模型权重，只对 LeRobot API 进行注入式写入/读回回归；**真实 LeRobot 包及 OpenPI 模型的数据加载尚未通过本版验收**。不得把假数据集测试描述为模型已能训练。外部 LeRobot API 见其 [官方数据集文档](https://huggingface.co/docs/lerobot/main/api/datasets)；升级上游版本时先复测兼容性。

## 标注到 LLaMA-Factory

```bash
python -m pip install -e '.[vlm]'
robot-learning build-vlm ./data/annotated ./data/vlm \
  --camera base --instruction 'What is the robot doing?' --stride 1
```

仅使用 `annotation.json` 中 `used_for_vlm=true` 的片段和指定相机。片段索引遵循**全局帧事件序号**，多相机时不等于采样步序号；`--stride` 在片段内该相机的帧上抽样。输出 `data.json`、`dataset_info.json` 和 PNG 图像，消息中的 `<image>` 数与路径一一对应，不复制旧目录中的硬编码任务、时间偏移或伪标签。见 [LLaMA-Factory 集成](../integrations/llamafactory/README.md)。当前只离线校验文件和样本，不宣称已加载到真实训练器。

本地 Python 3.14.6 环境使用 NumPy 2.5.1、h5py 3.16.0、Pillow 12.3.0 完成合成验证；其他 Python 版本由 CI 验证 HDF5/VLM 部分。输出目录/文件必须不存在，`data/` 默认被 `.gitignore` 排除。真实录制、模型权重、第三方框架源码都不应上传本仓库。
