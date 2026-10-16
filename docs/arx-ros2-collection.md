# ARX X5 ROS2 collection and offline replay

`v0.2.0` 迁移旧项目单臂 `RobotStatus` 与 ROS2 `sensor_msgs/Image` 的只读采集路径。公共包无 ROS2 依赖；仅 `collect-arx` 在运行时加载 `rclpy`、`sensor_msgs.msg` 与外部 `arx5_arm_msg.msg`。不复制 ARX 驱动、ROS 工作空间或编译产物。

## 配置与 Topic

`configs/arx_x5_ros2.json` 是示例。`follower_status_topic` 默认 `/arm_slave_l_status`，双路彩色相机是 `/camera_01/color/image_raw` 和 `/camera_02/color/image_raw`。这些 Topic 来自旧项目 `main/config.yaml`；使用单相机配置或不同命名空间时应修改 JSON。`doctor-arx` 只检查 Python 模块是否存在，不连接机械臂，也不能验证 Topic 内容。

旧 ROS2 `RobotStatus.msg` 定义 `joint_pos[7]`、`joint_vel[7]`。本版将前 6 维存为左臂关节，第 7 维单独存为夹爪；时间来自 `header.stamp.sec/nanosec`。只订阅**从臂反馈**，不把主臂反馈、从臂反馈或全零占位数据伪装为运动命令；生成的 Episode 没有 `ArmAction`。`joint_units` 和 `gripper_units` 在示例配置中显式标记 `*_unverified`，表示历史代码未给出可确认的物理单位。真实单位、零位、关节顺序与动作来源仍须人工对照设备文档及录制样本。

相机映射支持紧凑的 `rgb8`、`bgr8`、`mono8`、`mono16`、`16UC1` 原始图像；不做颜色转换，16 位编码保留字节序。压缩图像、行 padding、深度压缩格式不在本版支持范围。相机帧按 ROS2 header 时间与从臂状态做最近邻同步，超容差或缺帧整组丢弃，图像帧不会复用。要求各设备使用可比较的时钟源。

## 离线复现

```bash
python examples/collect_arx_synthetic.py ./data/arx-demo
robot-learning validate ./data/arx-demo
robot-learning preview-arx ./data/arx-demo
```

也可用 `robot-learning replay-arx-messages --config configs/arx_x5_ros2.json messages.jsonl ./data/arx-replay`。输入 JSONL 每行只有 `topic` 和 `message`；`message` 保留 ROS2 消息字段结构，例如 `header.stamp.sec/nanosec`、`joint_pos`/`joint_vel` 或 Image 的 `width`、`height`、`step`、`encoding`、`data`。这是用于测试的**脱敏消息夹具回放**，不是 rosbag2 解码器。输出目录须不存在。`preview-arx` 只校验并显示 Episode 的状态时间轴与单位，不发布 ROS2 消息，更不会运动机械臂。

## 可选实时采集

在已安装并 source ROS2 和 ARX 消息包的环境中：

```bash
robot-learning doctor-arx --config configs/arx_x5_ros2.json
robot-learning collect-arx --config configs/arx_x5_ros2.json ./data/arx-run-001
robot-learning validate ./data/arx-run-001
```

`collect-arx` 只创建 `RobotStatus`/`Image` 订阅，不创建命令发布器。`attempts` 是采集尝试数，不保证写入同样多的组；完成后检查 `written`/`dropped` 和相机预览。当前没有真机或授权录制样本，**未完成** Topic 连通性、时钟域、单位、夹爪量程、镜头映射、动作来源及安全停机的现场验收。本版仅为预发布，不开放真机回放或 `--execute`。
