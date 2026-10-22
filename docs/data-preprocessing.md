# Data preprocessing (v0.6.0)

此模块把旧项目常用的数据检查和平滑步骤拆成可组合函数和安全的文件转换命令。统计只报告数值，不推断单位；文件处理命令保留输入并写到一个新路径。

## Action statistics and normalization

`robot-learning action-stats episode.hdf5` 读取受支持的 `action`、`actions`、`action/joint_targets` 或旧 `joint_action/vector` 数据，输出每一维的样本数、最小值、最大值、均值和总体标准差。报告不会自动删异常值，也不把值解释为弧度、米或夹爪百分比。

Python API `action_statistics()`、`normalize_action()` 和 `denormalize_action()` 支持 `minmax` 与 `zscore`。归一化统计应从训练集计算并和模型 checkpoint 一起版本化；常量维归一化为 `0`，反归一化回常量值。调用者负责把统计和单位存入自己的训练配置。

## Gripper smoothing

```bash
robot-learning smooth-gripper-hdf5 source.hdf5 output-smoothed.hdf5 \
  --window-size 5 --threshold-ratio 0.05 --min-stable-frames 5
```

命令识别旧 `endpose/left_gripper`、`joint_action/left_gripper` 和 `joint_action/vector[:, 6]`。实现滑动窗口、开合端点稳定化和连续稳定帧锁定；参数显式可调。它复制原 HDF5 后再写入处理结果，输入不变；输出 HDF5 属性记录参数和实际处理字段。无可识别字段、非浮点夹爪数组或目标文件已存在时拒绝操作。

## MP4 frame import

```bash
python -m pip install -e '.[video]'
robot-learning preprocess-video episode_head_camera.mp4 episode.hdf5 episode-with-video.hdf5 \
  --camera head_camera --jpeg-quality 95
```

视频帧按首尾均匀抽样，数量与 HDF5 中 `joint_action/left_arm` 或 `action/joint_targets` 的步数一致，JPEG 写入 `observation/<camera>/rgb`。工具不覆盖输入 HDF5，也不伪造视频时间戳；输出属性记录相机名、JPEG 质量、抽帧方式及时间戳未保留的事实。视频无法解码、步数为零、相机数据集已存在或帧数不符时不会生成输出文件。

本版用假 OpenCV 后端验证解码调用、帧采样和 HDF5 写入逻辑；当前开发环境没有 OpenCV，因此真实 MP4 编解码还需在安装 `[video]` 的 CI/本机环境验证。
