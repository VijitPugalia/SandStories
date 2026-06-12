# MediaPipe 手模型接入方案

## 结论

不要继续把程序生成的 hologram 手当主视觉。更靠谱的路线是使用 Godot 官方 OpenXR hand tracking demo 里的 `LeftHandHumanoid.gltf` 和 `RightHandHumanoid.gltf`，再写一层 `MediaPipe 21 landmarks -> Godot Humanoid hand skeleton` 的 retargeting adapter。

这个方案的优点：

- 资产本来就是 Godot demo 用的 glTF skinned hand mesh，Web/Godot 导入路径比 FBX 稳。
- 骨骼命名是可维护的 humanoid hand 命名，例如 `RightIndexProximal`、`RightIndexIntermediate`、`RightIndexDistal`、`RightIndexTip`。
- 左右手是两个独立资产，不需要镜像一个手导致 winding、normal、骨骼朝向一起炸。
- 许可证来自 `godotengine/godot-demo-projects` 的 MIT license，集成风险比 Sketchfab 非商用模型低。
- 它和 Godot 的 `XRHandModifier3D` / WebXR / OpenXR 设计方向一致，后面如果要接真实 XR 手追踪也不会推倒重来。

推荐资产：

- `https://github.com/godotengine/godot-demo-projects/tree/master/xr/openxr_hand_tracking_demo/assets/gltf`
- `RightHandHumanoid.gltf`
- `RightHandHumanoid.bin`
- `LeftHandHumanoid.gltf`
- `LeftHandHumanoid.bin`
- `hand.png`

## 候选评估

### 1. Godot OpenXR Hand Tracking Demo

这是目前最适合我们的选择。Godot 官方文档说明 hand tracking 已经围绕 Godot Humanoid Skeleton 标准化，并且示例项目提供 properly rigged glTF hands。右手 glTF 里包含 25 个 joints：`RightHand`，每根手指的 `Metacarpal / Proximal / Intermediate 或 Distal / Tip`。这刚好适合把 MediaPipe 的 21 点转成骨骼旋转。

风险：

- 它不是“MediaPipe 直接吃”的资产，需要我们实现 landmark retargeting。
- 视觉风格是基础 XR 手，需要再套半透明材质、rim light、scanline 或 fresnel shader，才能变成我们想要的科技感。

### 2. `imadeddinedjekoune/Hand-Detection-3D`

这个仓库看起来最接近“MediaPipe + 3D 手模型”的现成项目，本地已检查：

- 本地候选资产：`assets/models/mediapipe_candidate/RightHand_CV.fbx`
- FBX 大小约 7.4 MB，带 `Tex_color.png` 和 `Tex_normal.png`。
- FBX 内部有 `Right Hand` mesh、`Armature`、数字命名 LimbNode。
- 骨骼链大致是 `0-1-2-3`、`5-6-7-8`、`9-10-12-13`、`14-15-16-17`、`18-19-20-21`。
- 它更像“Unity 项目里手动摆好的 demo rig”，并不是真正完整的 MediaPipe 21 点骨骼标准；缺 `4` 和 `11` 这样的 tip/intermediate 编号。

用途：

- 可以作为 retargeting 参考。
- 不建议作为主资产，除非 Godot 导入验证后效果明显比官方 glTF 好。

风险：

- README 说 MIT，但仓库根目录没有实际 `LICENSE` 文件。
- FBX 对 Godot/WebGL 不如 glTF 稳。
- Unity 脚本里是按子节点索引和欧拉角硬调，直接移植会很脆。

### 3. Sketchfab / 商店 rigged hand

能找到一些漂亮的 XR / anatomical rigged hand，例如 Sketchfab 上 2026 年的 anatomically accurate rigged hand。但很多是 `CC Attribution-NonCommercial` 或需要 attribution，实验内部看可以，论文 demo 或公开发包会有许可风险。

用途：

- 可以作为视觉参考。
- 不建议直接进入默认工程资产，除非确认许可和作者归属。

### 4. MANO

MANO 是研究级 parametric hand model，可以从 21 点拟合出更合理的手型和姿态。它的效果潜力最高，但接入复杂度也高：需要优化器/pose parameters/shape parameters，不是当前 Godot Web 原型最快路径。

用途：

- 后续如果论文需要“解剖合理性”和定量重建，可以考虑。
- 当前先别拿它做主线，不然会把互动原型拖进算法工程坑里。

## MediaPipe 到 Godot 手骨骼映射

MediaPipe Hands 标准 21 点：

- `0`: wrist
- `1,2,3,4`: thumb CMC, MCP, IP, tip
- `5,6,7,8`: index MCP, PIP, DIP, tip
- `9,10,11,12`: middle MCP, PIP, DIP, tip
- `13,14,15,16`: ring MCP, PIP, DIP, tip
- `17,18,19,20`: pinky MCP, PIP, DIP, tip

Godot humanoid hand 推荐映射：

| Godot bone | MediaPipe segment |
| --- | --- |
| `RightHand` / `LeftHand` | wrist `0` + palm basis from `0,5,9,17` |
| `ThumbMetacarpal` | `1 -> 2` |
| `ThumbProximal` | `2 -> 3` |
| `ThumbDistal` | `3 -> 4` |
| `ThumbTip` | follow `4` or keep bind pose |
| `IndexMetacarpal` | palm anchor `0 -> 5`, often keep bind rotation with mild splay |
| `IndexProximal` | `5 -> 6` |
| `IndexIntermediate` | `6 -> 7` |
| `IndexDistal` | `7 -> 8` |
| `IndexTip` | follow `8` or keep bind pose |
| `MiddleMetacarpal` | palm anchor `0 -> 9`, often keep bind rotation |
| `MiddleProximal` | `9 -> 10` |
| `MiddleIntermediate` | `10 -> 11` |
| `MiddleDistal` | `11 -> 12` |
| `MiddleTip` | follow `12` or keep bind pose |
| `RingMetacarpal` | palm anchor `0 -> 13`, mild splay |
| `RingProximal` | `13 -> 14` |
| `RingIntermediate` | `14 -> 15` |
| `RingDistal` | `15 -> 16` |
| `RingTip` | follow `16` or keep bind pose |
| `LittleMetacarpal` | palm anchor `0 -> 17`, mild splay |
| `LittleProximal` | `17 -> 18` |
| `LittleIntermediate` | `18 -> 19` |
| `LittleDistal` | `19 -> 20` |
| `LittleTip` | follow `20` or keep bind pose |

## Runtime 设计

### 数据层

继续用现在的 `hand_tracks` / `mediapipe_hands` 输入。每个 track 应该包含：

- `handedness`: `left` 或 `right`
- `samples`: 每帧 21 个 landmark
- `interpolation`: 默认 `cubic`，低质量实时输入可用 `linear`
- `landmark_space`: `world`、`image_depth` 或 `normalized`
- `confidence` / `visibility`: 可选，用来做手丢失时的 fade/hold

### 采样层

现有播放时间 `playhead` 不等于手数据 FPS。正确做法：

- 数据帧之间按时间戳重采样。
- landmark position 用 linear 或 Catmull-Rom。
- 骨骼 rotation 用 quaternion slerp。
- 渲染帧只消费“当前目标姿态”，不要假设每个 render frame 都有新的 MediaPipe frame。

### Retargeting 层

新增一个独立模块，例如 `scripts/hand_rig_retargeter.gd`：

- 启动时记录 skeleton bind pose。
- 每帧从 landmarks 计算 palm basis。
- 对每个骨骼计算 target direction。
- 将 target direction 转成相对 bind pose 的 local rotation。
- 加入 rotation clamp，避免 MediaPipe 抖动造成手指翻折。
- 用指数平滑或 damped slerp 解决数据 FPS 和渲染 FPS 不一致。

### 视觉层

不要让 hand model 本身长得像诊所教学模型。建议在 glTF mesh 上套一层 Godot 材质：

- 半透明 base alpha `0.45-0.65`
- fresnel rim 高亮
- 淡青/暖白边缘光，不要紫
- 手掌和指尖轻微 emissive
- 可选 scanline/noise，只做细腻流动，不做廉价赛博网格
- landmark skeleton 作为 debug overlay，默认关闭

## 下一步实施顺序

1. 拉取 Godot demo 的左右手 glTF/bin/texture 到 `assets/models/godot_humanoid_hands/`。
2. 加 `hand_rig_retargeter.gd`，先让 sample data 驱动右手，再驱动左手。
3. 保留现有 OBJ hand ghost 作为 fallback，把 procedural hologram 只留作 debug/实验选项。
4. 在 UI 里加 hand mode：`Rigged hand / Ghost mesh / Landmarks / Hidden`。
5. 加材质参数：透明度、rim strength、emission、smoothing、pose delay。
6. 浏览器里检查 WebGL 导入、帧率、手指朝向和左右手 handedness。
