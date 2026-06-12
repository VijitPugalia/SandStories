# 生产 Session 适配层

## 原则

生产端输出目录视为只读输入。Godot 工程不要求生产目录改命名、改格式、补字段或移动文件；所有兼容逻辑都放在 `tools/prepare_production_session.py` 和派生 cache 目录里。

本次验证的生产目录：

`res://assets/sessions/session_135BCEF0-09E6-4763-B724-F08493C95D3A`

目录内容：

- `manifest.json`: 生产 manifest，记录 RGB/depth/audio/stroke 路径和时间戳。
- `rgb/r_*.jpg`: 1920x1440 RGB 帧。
- `depth/d_*.png`: 256x192 16-bit 深度帧，`0..8m -> UInt16`。
- `strokes.json`: AR world 坐标绘制轨迹。
- `objects.jsonl`: 目标检测输出；当前样例为空。
- `audio.m4a`: AAC 音频；当前 manifest duration 为 0。

## 生成派生资源

运行：

```powershell
cd C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\SandStoriesGodot
python tools\prepare_production_session.py assets\sessions\session_135BCEF0-09E6-4763-B724-F08493C95D3A --project .
```

输出目录：

`res://assets/processed_sessions/session_135BCEF0-09E6-4763-B724-F08493C95D3A`

`assets/sessions/.gdignore` 会阻止 Godot 扫描和打包原始生产输入。运行时只依赖 `assets/processed_sessions/...`，避免 Godot 自动在生产目录里生成 `.import` 文件。

关键输出：

- `session.json`: Godot 运行时可直接读取的 session schema。
- `processed_manifest.json`: adapter 生成记录，每帧 RGB/depth/mask/cache 对应关系。
- `frame_contact_sheet.png`: QA 联系表，横向显示 5 帧的 clean RGB、clean depth 和 mask overlay，方便肉眼确认帧差异。
- `surface_mask.png`: 固定沙面有效区域，白色保留，黑色隐藏托盘外/非沙面。
- `occlusion_mask_*.png`: 每帧动态遮挡区域，白色表示手/身体/工具等遮挡。
- `mask_overlay_*.png`: QA 预览图，红色显示遮挡 mask，暗色显示非沙面区域。
- `clean_rgb_*.png`: 对齐到 depth 尺寸并去除遮挡后的 RGB。
- `clean_depth_*.png`: 对齐并去除遮挡后的高度图。

## 5 帧与高度解释

当前生产样例确实只有 5 个 RGB-D 采样帧。它们的时间大约在前 5 秒内，而 `strokes.json` 里的绘制轨迹开始得更晚，所以这批深度帧没有覆盖真正画沙/改沙面的阶段。

这也是为什么一开始“看起来没变化”：RGB 和遮挡 mask 在变，但 raw depth 的主要变化来自手、袖子或身体进入画面；adapter 生成 `clean_depth_*.png` 时会把这些遮挡区域回填掉，所以得到的是“无遮挡沙面高度”，自然会非常稳定。

为了让检查更明确，Web UI 左侧 `Depth / Material Fit` 里增加了 `Production Frame` 控件：

- `<` / `>` 可以逐帧切换。
- slider 可以手动拖到第 1 到第 5 帧。
- label 会显示当前帧号、生产 capture index、capture 时间和遮挡 mask 像素数。

深度高度归一化现在固定使用第一帧沙面区域的基线范围，而不是让每一帧各自缩放。当前样例的基线是 `p02=5775`、`p98=6415`，这样后续帧里的手/身体遮挡不会把高度图整体拉暗或拉亮。

## Mask 策略

当前实现是 SAM-like adapter，不依赖生产端修改：

- 用第一帧 RGB 估计稳定沙面区域，生成 `surface_mask`。
- 用深度前景突变、颜色变化、肤色/衣服特征和连通域过滤生成 `occlusion_mask`。
- 遮挡区域用上一帧 clean depth/RGB 回填；第一帧使用基准帧回填。
- 所有 mask 都保存在派生目录，生产目录不写入任何 cache。

后续如果接真正 SAM：

- 保持 `surface_mask.png` / `occlusion_mask_*.png` 输出契约不变。
- 只替换 `prepare_production_session.py` 内部 mask generator。
- Godot runtime 和生产 capture schema 不需要改。

## 在 Godot Web 打开

先 build：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_web.ps1
```

启动服务器：

```powershell
node tools\static_server.mjs build\web 8765 0.0.0.0
```

打开：

```text
http://127.0.0.1:8765/index.html?session=res%3A%2F%2Fassets%2Fprocessed_sessions%2Fsession_135BCEF0-09E6-4763-B724-F08493C95D3A%2Fsession.json
```

局域网访问时把 `127.0.0.1` 换成这台电脑的内网 IP。

## Godot 运行时接入点

- `scripts/main.gd` 支持 `?session=<res://.../session.json>` 启动参数。
- `assets/shaders/sand_depth.gdshader` 支持 `surface_mask`，非沙面区域会透明隐藏。
- `data/session_schema.json` 增加了可选字段 `surface_mask`、`occlusion_mask`、`processed_manifest`、`production_manifest`。

## 本次验证

- 原始生产目录保持 14 个生产文件；派生资源写入 `assets/processed_sessions/...`。
- Web 打包只包含 processed cache，不包含 raw production RGB/depth/audio。
- JSON 合法性已验证。
- Godot headless import 已通过。
- Web export 已通过。
- 浏览器加载生产派生 session 后 canvas 正常，控制台没有 warning/error。
