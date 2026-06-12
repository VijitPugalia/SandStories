# Sand Stories 实现解释与接入指南

这份文档用更直白的方式解释：现在这个原型到底做了什么、为什么这么做、以及下一步怎样把真实数据接进来。

## 1. 现在已经能做什么

当前 WebGL 原型已经具备一套最小但完整的研究平台骨架：

- 能加载静态深度图和材质图，生成 3D 沙面。
- 能切换到 OGV 深度/材质视频流，shader 接口和静态图共用。
- 能显示左右手独立 track，每只手有自己的模型、21 点 landmark 和骨架线。
- 能兼容 MediaPipe-style 21 点关键点。
- 能显示 session 里的对象、沙面区域、手势事件和 referential links。
- 能切换 Stage 1 / Stage 2 condition，用来做 ablation-style study。
- 能记录 evidence marker 和 response draft。
- 能导出并跑在浏览器 WebGL 里。

这不是最终论文系统，但它已经把 method 里面最麻烦的几个接口位置占住了：RGB-D reconstruction、gesture trace、object/reference annotation、study probe。

## 2. 两个左手是怎么修掉的

原始 `hands.obj` 里有两只手，是一个双手模型。研究平台里我们不能继续把它当一个整体用，因为真实数据里每只手应该是一个独立 track，可以单独隐藏、单独绑定 MediaPipe、单独连到 reference link。

现在处理方式是：

1. `tools/split_hands_obj.py` 读取原始 `assets/models/hands.obj`。
2. 它按每个 face 的 X 方向 centroid 把 mesh 分成左右两组。
3. 输出 `assets/models/hand_left.obj` 和 `assets/models/hand_right.obj`。
4. `session.json` 的 `hand_tracks` 分别绑定左右手模型。
5. `tools/refresh_sample_hand_tracks.py` 重新生成 demo 关键点，右手 local template 做 X mirror。

也就是说，现在不是“把两个一样的左手摆在两个位置”，而是：

- 右手 track：`right_hand`，`handedness: "right"`，模型 `hand_right.obj`，关键点已镜像。
- 左手 track：`left_hand`，`handedness: "left"`，模型 `hand_left.obj`，关键点保持左手形态。

后面接真实 MediaPipe 时，不需要再用这个 demo 生成器。真实 pipeline 应该直接输出每帧 landmarks；只要 handedness 和坐标是对的，runtime 会按 track 显示。

## 3. 推荐的数据包结构

后面每一个真实 participant/session，建议整理成类似这样：

```text
sessions/
  participant_001_story_01/
    session.json
    depth_stream.ogv
    texture_stream.ogv
    top_rgb.ogv
    front_rgb.ogv
    audio.ogg
    notes/
      elan_export.csv
      calibration.json
```

Godot 当前样例还放在 `data/sample_session/session.json`，但工程上最终应该支持 session chooser 或 URL 参数指定 session package。

## 4. 接深度图和沙面材质图

最小输入是两张对齐图片：

- depth/height map：灰度图，亮度表示高度。
- texture/material map：RGB 图，和 depth map 同一视角、同一裁切、同一分辨率或可用 UV scale 对齐。

`session.json` 写法：

```jsonc
{
  "data_sources": {
    "use_video_streams": false,
    "depth_map": "res://assets/heightmaps/sand2_heightmap_square_lowfreq.png",
    "texture_map": "res://assets/source_images/sand2_original_square.png",
    "depth_video": "res://assets/video/depth_stream.ogv",
    "texture_video": "res://assets/video/texture_stream.ogv",
    "calibration": {
      "depth_uv_offset": [0.0, 0.0],
      "texture_uv_offset": [0.0, 0.0],
      "depth_uv_scale": [1.0, 1.0],
      "texture_uv_scale": [1.0, 1.0],
      "height_scale": 1.0,
      "material_strength": 0.0
    }
  }
}
```

如果要吃视频流：

1. 把 depth video 和 texture video 转成 `.ogv`。
2. 保证两条视频同 fps、同 duration、同 frame count。
3. 在 `data_sources` 里填 `depth_video` 和 `texture_video`。
4. 把 `use_video_streams` 设为 `true`，或在浏览器 URL 加 `?video=1`。

视频播放器节点现在是隐藏的，只作为 texture source 给 shader 用。这个设计是故意的：否则 Godot 的 `VideoStreamPlayer` 会像普通 UI 控件一样把视频画在屏幕上，造成一个奇怪的中央图片。

## 5. 接 MediaPipe 手部关键点

推荐格式是 `hand_tracks`，因为它最适合研究数据：每只手一个 track，track 里是按时间排列的 sample。

```jsonc
{
  "hand_tracks": [
    {
      "id": "right_hand",
      "label": "Right hand / drawing gesture",
      "handedness": "right",
      "model_path": "res://assets/models/hand_right.obj",
      "model_scale": 0.9,
      "model_rotation_degrees": [-90.0, 12.0, 0.0],
      "model_follow_orientation": true,
      "virtual_hand": true,
      "show_landmarks": false,
      "show_skeleton": false,
      "show_mesh_ghost": false,
      "interpolation": "cubic",
      "color": "#57c7d4",
      "mesh_color": "#57c7d4",
      "joint_count": 21,
      "samples": [
        {
          "time": 0.0,
          "landmarks": [
            [-1.25, 0.34, -0.62],
            [-1.18, 0.35, -0.58],
            "... 19 more MediaPipe points ..."
          ]
        }
      ]
    }
  ]
}
```

如果你的 preprocessing 更自然地产生“每一帧里有几只手”，也可以用 `mediapipe_hands`：

```jsonc
{
  "mediapipe_hands": [
    {
      "time": 0.0,
      "hands": [
        {
          "id": "right_hand",
          "label": "Right hand",
          "handedness": "right",
          "landmarks": [
            [-1.25, 0.34, -0.62],
            "... 20 more points ..."
          ]
        },
        {
          "id": "left_hand",
          "label": "Left hand",
          "handedness": "left",
          "landmarks": [
            [1.15, 0.36, -0.95],
            "... 20 more points ..."
          ]
        }
      ]
    }
  ]
}
```

Runtime 会把 `mediapipe_hands` 自动整理成 `hand_tracks`，所以两种都能显示。

手部时间轴会按 `time` 在相邻 samples 之间重采样。默认 `interpolation: "cubic"`，适合 capture fps 和 WebGL render fps 不一致的情况；如果你想严格看原始逐帧输出，可以改成 `nearest`，如果真实数据噪声比较大也可以先用 `linear`。

默认 `virtual_hand: true` 会从 21 个 landmarks 生成一只半透明 hologram 手，正式展示时不会看到一堆关键点。需要检查 MediaPipe 输出时，把 `show_landmarks` 或 `show_skeleton` 临时设成 `true` 就能打开调试层。

### 坐标约定

Godot 里当前约定：

- `x`：沙面横向。
- `z`：沙面纵深。
- `y`：高度。

MediaPipe 原始输出通常是 image-normalized coordinates 或 camera/world landmarks。不要直接丢进 Godot。需要先做：

1. 从 RGB/depth 相机坐标转到沙面坐标。
2. 根据标定矩阵/四角点，把 image plane 映射到 Godot sand plane。
3. 把深度或估计高度写到 `y`。
4. 保证单位和 `surface_scale` 接近，否则手会巨大或很小。

最粗暴但有效的第一版可以先只做 2D 映射：

```text
godot_x = (u - 0.5) * surface_world_width
godot_z = (v - 0.5) * surface_world_depth
godot_y = estimated_height_above_sand
```

后面再替换成真正的 camera calibration。

## 6. 接对象、工具和实体

对象层适合接两类东西：

- 实体物品：toy、tool、card、figurine。
- 语义对象：child 画出来并持续引用的 story object。

最小格式：

```jsonc
{
  "objects": [
    {
      "id": "bridge_block",
      "label": "Bridge block",
      "primitive": "box",
      "position": [0.8, 0.18, -0.4],
      "size": [0.45, 0.18, 0.2],
      "color": "#f0b35a"
    }
  ]
}
```

如果后面有真实模型：

```jsonc
{
  "id": "animal_figure",
  "label": "Animal figure",
  "model_path": "res://assets/models/animal_figure.glb",
  "position": [1.1, 0.2, 0.3],
  "size": [1.0, 1.0, 1.0]
}
```

目前 primitive 是为了先跑通研究逻辑。真正视觉质量可以后面再换 GLB。

## 7. 接标注和 reference links

method 里的重点不是只看哪里有手，而是看 gesture、speech、sand mark、object 怎么互相构成意义。所以数据里需要三类解释层。

`surface_regions` 表示沙面上被画出来或可被引用的区域：

```jsonc
{
  "surface_regions": [
    {
      "id": "river_path",
      "label": "River path",
      "position": [-0.4, 0.04, 0.2],
      "size": [1.4, 0.35],
      "rotation_degrees": 18,
      "start": 1.0,
      "end": 12.0,
      "color": "#57c7d4"
    }
  ]
}
```

`gesture_events` 表示编码后的手势片段：

```jsonc
{
  "gesture_events": [
    {
      "id": "draw_river",
      "kind": "drawing",
      "label": "Draws the river route",
      "start": 1.2,
      "end": 4.8,
      "target": "river_path"
    }
  ]
}
```

`references` 表示某个 source 指向某个 target：

```jsonc
{
  "references": [
    {
      "id": "gesture_to_river",
      "source": "right_hand",
      "target": "river_path",
      "start": 1.2,
      "end": 4.8,
      "color": "#57c7d4"
    }
  ]
}
```

`source` 可以是 hand id、object id、annotation id；`target` 可以是 surface region、object 或 annotation。Runtime 会在对应时间段显示 link line。

## 8. 接中文姓名和 Unicode 文本

如果后面 session 里有很多中国 participant，建议把名单写进 `participants`。可以是简单字符串，也可以是对象：

```jsonc
{
  "participants": [
    "张伟",
    "王芳",
    {
      "id": "p03",
      "display_name": "李娜",
      "role": "participant"
    }
  ]
}
```

当前原型已经打包 `assets/fonts/NotoSansSC-VF.ttf`，UI 和 3D 标注都会使用它，所以中文姓名、中文任务、中文标点、顿号、换行在 WebGL 里不再依赖系统默认字体。

快速 smoke test：

```text
http://127.0.0.1:8765/index.html?unicode=1
```

这个模式会临时显示 40 个中文姓名，并写入一条包含中文的 `unicode_smoke_test` 日志。正式数据不要把姓名硬编码进脚本，应该写进 `session.json` 或后处理生成的 session package。

如果只想检查字体和 JSON，不开浏览器，可以跑：

```powershell
& "C:\Users\lj200\Documents\Tools\Godot_v4.5.1-stable_mono_win64\Godot_v4.5.1-stable_win64_console.exe" --headless --path "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\SandStoriesGodot" --script "res://tools/unicode_font_check.gd"
```

## 9. 怎么运行

Godot 编辑器运行：

```powershell
& "C:\Users\lj200\Documents\Tools\Godot_v4.5.1-stable_mono_win64\Godot_v4.5.1-stable_win64_console.exe" --path "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\SandStoriesGodot"
```

WebGL 导出：

```powershell
cd C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\SandStoriesGodot
.\tools\build_web.ps1
```

本地浏览：

```text
http://127.0.0.1:8765/index.html
```

常用 URL：

```text
http://127.0.0.1:8765/index.html?condition=stage2
http://127.0.0.1:8765/index.html?condition=no_gestures
http://127.0.0.1:8765/index.html?video=1
http://127.0.0.1:8765/index.html?view=top
http://127.0.0.1:8765/index.html?unicode=1
```

## 10. 调试 checklist

如果画面不对，可以按这个顺序查：

- 沙面完全不显示：先查 `depth_map` / `texture_map` 路径是不是 Godot `res://` 路径。
- 中间出现一块莫名其妙的视频图：检查 video player 是否被当 UI 显示；当前版本已隐藏。
- 手不显示：查 `hand_tracks` 是否存在、每个 sample 是否有 `landmarks` 或 `joints`。
- 两只手长得同向：查右手 landmarks 是否真的做了 mirror 或来自真实 handedness 数据。
- 手巨大/很小：查 MediaPipe 到 Godot 的坐标尺度。
- 手飘在沙面外：查 image-to-sand-plane calibration。
- reference link 不亮：查 `references.start/end` 是否覆盖当前时间，`source/target` id 是否存在。
- 视频流不更新：查 `.ogv` 是否能被 Godot Web 播放，depth/material 两条视频是否同长度。
- 中文姓名显示成方块：查 `assets/fonts/NotoSansSC-VF.ttf` 是否被导出，或打开 `?unicode=1` 做 CJK smoke test。
- 中文输入没进日志：先确认 TextEdit 有焦点，再点 `Log response draft`；Web 输入法行为仍建议用目标浏览器实测。
- 浏览器黑屏：查 Godot export template、浏览器 console、`index.pck` 是否和最新构建一致。

## 11. 我建议下一步怎么弄

最稳的路线不是先做花哨 UI，而是先做一个可重复的数据接入链：

1. 定义真实 session folder 结构。
2. 写一个 preprocessing script，把 depth/material/top/front/audio/MediaPipe/ELAN 输出全部整理到一个 `session.json`。
3. 写一个 validator，在进入 Godot 前发现路径、时间戳、landmark 数量、handedness、坐标范围问题。
4. 在 Godot 里加 session selector 和 calibration save。
5. 把 researcher debug UI 和 participant-facing UI 拆开。
6. 最后再做正式 experiment visual polish 和 logging dashboard。

这样做的好处是：我们不会被某一个 demo asset 卡死。真实研究数据一来，只要能产出同一份 session contract，Godot 端就可以继续工作。
