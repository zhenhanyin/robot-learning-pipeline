# Control and legacy replay (v0.6.0 pre-release)

本阶段把旧 Piper ROS1 控制接口、Piper CAN 关节/夹爪命令和 ARX `RobotCmd` 回放拆成可注入的模块；**不把这些代码称为已经真机验收**。ROS、SDK、模型框架均由各自环境安装，ROS1 与 ROS2 不在同一进程中启动。

## Old ARX HDF5

旧 `joint_action/left_arm`、`left_gripper` 来自旧采集脚本读到的关节状态，不保证是真正已下发的目标动作。旧文件没有逐帧时间戳；导入时必须提供原采样帧率，生成的时间轴只可用于离线对照。默认自动导入文件中存在的所有受支持 RGB 相机，保留 `endpose/left_endpose` 和各相机逐帧 `intrinsic_cv`、`extrinsic_cv`、`cam2world_gl`。标定和末端姿态单位仍标为未确认。旧示例的 `pointcloud` 形状为 `(140, 0)`；空字段会写入来源说明，非空点云在点格式确认前拒绝导入。

```bash
python -m pip install -e '.[hdf5,vlm]'
robot-learning import-arx-legacy /path/to/episode.hdf5 ./data/arx-import --rate 30
robot-learning validate ./data/arx-import
robot-learning replay-arx-hdf5 /path/to/episode.hdf5 --rate 30
```

导入 Episode 记录左臂关节状态、可用的末端姿态、RGB 图像和相机标定，不伪造动作。训练导出如需 `next-state`，必须显式使用 `--action-policy next-state`，并确认动作语义。`replay-arx-hdf5` 默认只输出选中帧数，`published=0`；`--noop-threshold` 可按关节变化范数过滤静止帧，保留夹爪变化，发布时保留过滤造成的时间间隔。

实时 `collect-arx` 也可在原采集 JSON 配置里添加可选 `noop_joint_threshold`；默认 `0` 不过滤，正值按原始关节单位比较与上一个保留状态的欧氏距离，夹爪变化不会被丢弃。跳过的状态计入 `dropped`，不是采集失败；阈值不能直接照搬旧脚本归一化空间的 `1e-4`。

## Optional ROS2 publishing

`replay-arx-hdf5 --publish --limits /path/to/limits.json` 才导入 ROS2 `RobotStatus`/`RobotCmd`、订阅当前状态并向配置的 Topic 发布。配置 JSON 必填：`topic`、`status_topic`、`rate_hz`、`joint_units`、`gripper_units`、六元素 `joint_min`/`joint_max`/`max_joint_step`、`gripper_min`/`gripper_max`/`max_gripper_step`、`max_observation_age_ms`。必须根据本机 SDK、标定、控制模式和现场限位填写，不提供可直接使用的通用数值。字符串写成 `rad` 等并不能自动验证文件实际单位；代码不做隐式换算。旧脚本 `RobotCmd.mode=5` 由命令适配器保留。`--interpolation-steps N` 从订阅到的当前状态向首帧生成 N 步插值；每步读取最新状态并检查时间年龄、限位和最大步长，检查失败停止继续发布。

这不是设备急停或安全认证。命令一旦发出，驱动是否执行、是否停止，需要设备侧独立确认。发布路径只完成注入式假消息测试，未连接真实控制器。

## Piper CAN and ROS1 Web

`PiperCommandAdapter` 由调用者注入已经连接的 SDK、关节和夹爪的单位到原始 tick 比例。先调用 `enable()`：它调用旧 SDK 的 `EnableArm(7)`，最多等待 5 秒核对 6 个电机的使能反馈，再切入关节控制模式；反馈不足就拒绝发送。之后才可通过 `send_command()` 发送 6 关节及可选夹爪命令；`stop()` 调用 SDK 的 `MotionCtrl_1` 停机指令。调用者必须在发送前使用 `dispatch_commands()` 的状态时效、限位和步长检查，并核对 SDK 固件对这些命令的解释。

```bash
robot-learning control-web --port 8767
```

该命令需要已配置的 ROS1 `rospy`、`std_srvs`、`std_msgs` 环境。Web 仅监听 `127.0.0.1`；`GET /api/query_switch`、`/api/query_status`、`/api/query_record_num` 对应旧 `/piper_collect_data/*` 服务；`POST /api/set_switch` 接收 `{"switch_state": true}`。旧动作 Topic 包括 `sweep`、`clean`、`vllm`、`move_left`、`move_right`、`dump`、`put_plate`、`sweep_all`、`return_initial_position`、`pick_up_the_plate`，统一用空 JSON 对象 POST 到 `/api/<name>`；`vla` 和 `return_to_init_pos` 亦如此。`POST /api/obj` 接收 `{"text":"..."}`。旧接口的 `return_to_init_pos` 实际发布 `/is_stop/` 的 `Bool(true)`，不能根据名称推断会自动回零。Web 不公开旧页、不允许 CORS 通配，也没有远程鉴权；不要通过端口转发或反向代理暴露到公网。

`load_policy()` 可用 `module:factory` 加载用户安装的 ACT、H-RDT、π0/π0.5 后端，检查所需调用方法，并选 RGB 数组或原始图像字节。只可加载受信任的本地模块：工厂会在本进程执行。它**不**处理 checkpoint 的归一化、填零、颜色空间或实时看门狗；调用者提供与 checkpoint 一致的预处理。`TaskOrchestrator.execute(adapter, proposal_id)` 提供代码级、批准后执行入口；合成任务 Web 仍只有预览，没有执行 HTTP 端点。真实语音/VLM/VLA 和旧 GUI 缺失的 `lib/` 不在仓库内。

Piper 旧目录导入会在存在 `follower_endpose` 时按时间戳同步，并保存六维 `xyz_rpy` 原始值；可选深度 PNG 标记为 `depth`，不改写成 RGB。单位或坐标系不明时保留未确认标记。

动作统计、夹爪平滑和 MP4 预处理见[数据预处理](data-preprocessing.md)。视频命令使用 OpenCV，按 HDF5 动作步数均匀抽帧后写入新文件；旧数据不含可对齐的视频时间戳，导出清单会注明源时间戳未保留。
