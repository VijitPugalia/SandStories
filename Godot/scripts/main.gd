extends Node3D

const DEFAULT_SESSION_PATH := "res://data/sample_session/session.json"
const LOG_PATH := "user://interaction_log.jsonl"
const HAND_MODEL_LEFT_PATH := "res://assets/models/hand_left.obj"
const HAND_MODEL_RIGHT_PATH := "res://assets/models/hand_right.obj"
const SAND_SHADER_PATH := "res://assets/shaders/sand_surface.gdshader"
const SAND_DEPTH_SHADER_PATH := "res://assets/shaders/sand_depth.gdshader"
const HAND_HOLOGRAM_SHADER_PATH := "res://assets/shaders/hologram_hand.gdshader"
const CJK_FONT_PATH := "res://assets/fonts/NotoSansSC-VF.ttf"
const FONT_WEIGHT_AXIS := 0x77676874 # "wght"
const SAND_HEIGHTMAP_PATH := "res://assets/heightmaps/sand2_heightmap_square_lowfreq.png"
const SAND_TEXTURE_PATH := "res://assets/source_images/sand2_original_square.png"
const SAND_DEPTH_VIDEO_PATH := "res://assets/video/depth_stream.ogv"
const SAND_TEXTURE_VIDEO_PATH := "res://assets/video/texture_stream.ogv"
const MEDIAPIPE_HAND_BONES := [
	[0, 1], [1, 2], [2, 3], [3, 4],
	[0, 5], [5, 6], [6, 7], [7, 8],
	[0, 9], [9, 10], [10, 11], [11, 12],
	[0, 13], [13, 14], [14, 15], [15, 16],
	[0, 17], [17, 18], [18, 19], [19, 20],
	[5, 9], [9, 13], [13, 17]
]
const VIRTUAL_HAND_SEGMENTS := [
	[0, 1], [1, 2], [2, 3], [3, 4],
	[0, 5], [5, 6], [6, 7], [7, 8],
	[0, 9], [9, 10], [10, 11], [11, 12],
	[0, 13], [13, 14], [14, 15], [15, 16],
	[0, 17], [17, 18], [18, 19], [19, 20]
]
const VIRTUAL_HAND_TIPS := [4, 8, 12, 16, 20]
const HAND_PALM_TRIANGLES := [
	[0, 5, 9],
	[0, 9, 13],
	[0, 13, 17],
	[5, 9, 13],
	[5, 13, 17]
]

var session := {}
var data_sources := {}
var duration := 1.0
var playhead := 0.0
var is_playing := false
var camera_yaw := -0.15
var camera_pitch := -1.42
var camera_distance := 9.6
var camera_target := Vector3.ZERO
var camera_move_velocity := Vector3.ZERO
var is_rotating := false
var is_panning := false
var last_mouse_position := Vector2.ZERO
var use_video_streams := false
var unicode_smoke_test_enabled := false
var ui_font: Font
var ui_font_strong: Font
var ui_font_display: Font

var camera: Camera3D
var sand_layer: Node3D
var gesture_layer: Node3D
var object_layer: Node3D
var annotation_layer: Node3D
var highlight_layer: Node3D
var relation_layer: Node3D
var sand_mesh_instance: MeshInstance3D
var heightmap_surface_node: MeshInstance3D
var heightmap_material: ShaderMaterial
var static_depth_texture: Texture2D
var static_surface_texture: Texture2D
var static_surface_mask_texture: Texture2D
var depth_video_player: VideoStreamPlayer
var texture_video_player: VideoStreamPlayer
var processed_surface_frames: Array = []
var processed_surface_base_dir := ""
var surface_frame_index := -1
var hand_tracks: Array = []
var hand_track_roots := {}
var hand_model_nodes := {}
var hand_joint_nodes := {}
var hand_bone_nodes := {}
var hand_virtual_nodes := {}
var hand_rendered_points := {}
var object_nodes: Array[MeshInstance3D] = []
var annotation_nodes: Array[Node3D] = []
var highlight_nodes: Array[Node3D] = []
var relation_nodes: Array[MeshInstance3D] = []
var object_nodes_by_id := {}
var annotation_nodes_by_id := {}
var current_condition := "baseline"

var play_button: Button
var time_slider: HSlider
var time_label: Label
var condition_option: OptionButton
var task_label: Label
var participant_label: Label
var evidence_label: Label
var response_notes: TextEdit
var source_status_label: Label
var surface_frame_label: Label
var surface_frame_slider: HSlider
var active_event_label: Label
var hand_status_label: Label
var video_stream_toggle: CheckBox
var focus_button: Button
var reference_views_button: Button
var modality_panel: PanelContainer
var study_panel: PanelContainer
var lower_dock_panel: Panel
var fixed_views_panel: PanelContainer
var top_viewport: SubViewport
var front_viewport: SubViewport
var top_view_camera: Camera3D
var front_view_camera: Camera3D
var layer_toggles := {}
var surface_sliders := {}
var focus_mode := false
var reference_views_visible := false
var surface_controls := {
	"depth_u": 0.0,
	"depth_v": 0.0,
	"texture_u": 0.0,
	"texture_v": 0.0,
	"displacement": 1.0,
	"material_strength": 0.0
}


func _ready() -> void:
	_load_text_font()
	_build_world()
	_build_ui()
	_load_session(DEFAULT_SESSION_PATH)
	_apply_launch_params()
	_apply_condition(current_condition)
	_update_scene_from_time()
	_update_camera()
	_log_event("prototype_ready", {})


func _load_text_font() -> void:
	var base_font: Font
	if ResourceLoader.exists(CJK_FONT_PATH):
		var font_resource := load(CJK_FONT_PATH)
		if font_resource is Font:
			base_font = font_resource

	if base_font == null:
		var system_font := SystemFont.new()
		system_font.font_names = PackedStringArray([
			"Noto Sans SC",
			"Microsoft YaHei UI",
			"Microsoft YaHei",
			"DengXian",
			"SimHei",
			"Arial Unicode MS",
			"sans-serif"
		])
		base_font = system_font

	ui_font = _font_variation(base_font, 0.18, 460.0)
	ui_font_strong = _font_variation(base_font, 0.28, 560.0)
	ui_font_display = _font_variation(base_font, 0.36, 640.0)


func _font_variation(base_font: Font, embolden: float, weight: float) -> Font:
	var variation := FontVariation.new()
	variation.base_font = base_font
	variation.variation_opentype = {FONT_WEIGHT_AXIS: weight}
	variation.variation_embolden = embolden
	return variation


func _process(delta: float) -> void:
	_update_keyboard_camera(delta)
	if is_playing:
		playhead += delta
		if playhead >= duration:
			playhead = duration
			is_playing = false
			play_button.text = "Play"
		time_slider.value = playhead
		_update_scene_from_time()


func _input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if _is_pointer_over_ui():
			return
		if event.button_index == MOUSE_BUTTON_LEFT:
			is_rotating = event.pressed and not event.shift_pressed
			is_panning = event.pressed and event.shift_pressed
			last_mouse_position = event.position
			_set_input_handled()
		elif event.button_index == MOUSE_BUTTON_RIGHT:
			is_rotating = event.pressed
			last_mouse_position = event.position
			_set_input_handled()
		elif event.button_index == MOUSE_BUTTON_MIDDLE:
			is_panning = event.pressed
			last_mouse_position = event.position
			_set_input_handled()
		elif event.button_index == MOUSE_BUTTON_WHEEL_UP and event.pressed:
			_zoom_camera(-0.55)
			_set_input_handled()
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
			_zoom_camera(0.55)
			_set_input_handled()
	elif event is InputEventMouseMotion:
		var mouse_delta: Vector2 = event.position - last_mouse_position
		last_mouse_position = event.position
		if is_rotating:
			camera_yaw -= mouse_delta.x * 0.008
			camera_pitch = clamp(camera_pitch - mouse_delta.y * 0.008, -1.48, -0.15)
			_update_camera()
			_set_input_handled()
		elif is_panning:
			_pan_camera((-mouse_delta.x * 0.012), (mouse_delta.y * 0.012))
			_set_input_handled()
	elif event is InputEventKey and event.pressed and not event.echo:
		if _text_input_has_focus():
			return
		_handle_keyboard_camera(event.keycode)


func _is_pointer_over_ui() -> bool:
	var hovered := get_viewport().gui_get_hovered_control()
	return hovered != null and hovered.mouse_filter != Control.MOUSE_FILTER_IGNORE


func _text_input_has_focus() -> bool:
	var focus := get_viewport().gui_get_focus_owner()
	return focus is TextEdit or focus is LineEdit


func _set_input_handled() -> void:
	get_viewport().set_input_as_handled()


func _update_keyboard_camera(delta: float) -> void:
	if camera == null:
		return
	if _text_input_has_focus():
		camera_move_velocity = camera_move_velocity.move_toward(Vector3.ZERO, 18.0 * delta)
		return

	var move := Vector3.ZERO
	var forward := -camera.global_transform.basis.z
	forward.y = 0.0
	forward = forward.normalized() if forward.length() > 0.001 else Vector3.FORWARD
	var right := camera.global_transform.basis.x
	right.y = 0.0
	right = right.normalized() if right.length() > 0.001 else Vector3.RIGHT

	if Input.is_key_pressed(KEY_W) or Input.is_key_pressed(KEY_UP):
		move += forward
	if Input.is_key_pressed(KEY_S) or Input.is_key_pressed(KEY_DOWN):
		move -= forward
	if Input.is_key_pressed(KEY_D) or Input.is_key_pressed(KEY_RIGHT):
		move += right
	if Input.is_key_pressed(KEY_A) or Input.is_key_pressed(KEY_LEFT):
		move -= right

	var boost := 2.1 if Input.is_key_pressed(KEY_SHIFT) else 1.0
	var base_speed: float = clamp(camera_distance * 0.85, 3.2, 16.0)
	var target_velocity := Vector3.ZERO
	if move.length() > 0.001:
		target_velocity = move.normalized() * base_speed * boost
	camera_move_velocity = camera_move_velocity.move_toward(target_velocity, base_speed * 8.0 * delta)
	if camera_move_velocity.length() > 0.01:
		camera_target += camera_move_velocity * delta
		_update_camera()


func _zoom_camera(delta: float) -> void:
	camera_distance = clamp(camera_distance + delta, 1.8, 26.0)
	_update_camera()
	_log_event("camera_zoom", {"distance": camera_distance})


func _pan_camera(x_amount: float, y_amount: float) -> void:
	var right := camera.global_transform.basis.x
	var up := camera.global_transform.basis.y
	camera_target += (right * x_amount + up * y_amount) * max(0.6, camera_distance * 0.12)
	_update_camera()


func _handle_keyboard_camera(keycode: int) -> void:
	match keycode:
		KEY_Q:
			_zoom_camera(-0.65)
		KEY_E:
			_zoom_camera(0.65)
		KEY_R:
			_set_camera_preset("orbit")
		KEY_TAB:
			_toggle_focus_mode()
		KEY_1:
			_set_camera_preset("top")
		KEY_2:
			_set_camera_preset("front")
		KEY_3:
			_set_camera_preset("orbit")
		_:
			return
	_set_input_handled()


func _set_camera_preset(preset: String) -> void:
	match preset:
		"top":
			camera_yaw = 0.0
			camera_pitch = -1.32
			camera_distance = 6.5
			camera_target = Vector3.ZERO
		"front":
			camera_yaw = 0.0
			camera_pitch = -0.25
			camera_distance = 7.0
			camera_target = Vector3.ZERO
		_:
			camera_yaw = -0.15
			camera_pitch = -1.42
			camera_distance = 9.6
			camera_target = Vector3.ZERO
	_update_camera()
	_log_event("camera_preset", {"preset": preset})


func _build_world() -> void:
	var light := DirectionalLight3D.new()
	light.name = "Sun"
	light.rotation_degrees = Vector3(-55, 35, 0)
	light.light_energy = 2.8
	add_child(light)

	var environment := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.78, 0.82, 0.78)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.65, 0.68, 0.62)
	env.ambient_light_energy = 0.8
	environment.environment = env
	add_child(environment)

	camera = Camera3D.new()
	camera.name = "Camera"
	camera.fov = 42
	add_child(camera)

	sand_layer = Node3D.new()
	sand_layer.name = "SandSurfaceLayer"
	add_child(sand_layer)

	gesture_layer = Node3D.new()
	gesture_layer.name = "GestureLayer"
	add_child(gesture_layer)

	object_layer = Node3D.new()
	object_layer.name = "ObjectLayer"
	add_child(object_layer)

	annotation_layer = Node3D.new()
	annotation_layer.name = "AnnotationLayer"
	add_child(annotation_layer)

	highlight_layer = Node3D.new()
	highlight_layer.name = "SandHighlightLayer"
	annotation_layer.add_child(highlight_layer)

	relation_layer = Node3D.new()
	relation_layer.name = "ReferentialRelationLayer"
	annotation_layer.add_child(relation_layer)


func _build_ui() -> void:
	var canvas := CanvasLayer.new()
	canvas.name = "HUD"
	add_child(canvas)

	var hud_root := Control.new()
	hud_root.name = "HUDRoot"
	hud_root.set_anchors_preset(Control.PRESET_FULL_RECT)
	hud_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	if ui_font != null:
		var cjk_theme := Theme.new()
		cjk_theme.set_default_font(ui_font)
		cjk_theme.set_default_font_size(15)
		hud_root.theme = cjk_theme
	canvas.add_child(hud_root)

	var top_bar := PanelContainer.new()
	top_bar.name = "TopBar"
	top_bar.add_theme_stylebox_override("panel", _panel_style(Color(0.045, 0.052, 0.048, 0.96), 14))
	top_bar.anchor_left = 0.0
	top_bar.anchor_top = 0.0
	top_bar.anchor_right = 1.0
	top_bar.anchor_bottom = 0.0
	top_bar.offset_left = 16
	top_bar.offset_top = 12
	top_bar.offset_right = -16
	top_bar.offset_bottom = 72
	hud_root.add_child(top_bar)

	var top_row := HBoxContainer.new()
	top_row.add_theme_constant_override("separation", 14)
	top_bar.add_child(top_row)

	var title_box := VBoxContainer.new()
	title_box.custom_minimum_size = Vector2(300, 0)
	top_row.add_child(title_box)

	var title := Label.new()
	title.text = "Sand Stories Lab"
	_apply_text_style(title, ui_font_display, 24)
	title.add_theme_color_override("font_color", Color(0.93, 0.91, 0.82))
	title_box.add_child(title)

	var subtitle := Label.new()
	subtitle.text = "RGB-D reconstruction / hand semantics / evidence capture"
	_apply_text_style(subtitle, ui_font_strong, 13)
	subtitle.add_theme_color_override("font_color", Color(0.58, 0.72, 0.69))
	title_box.add_child(subtitle)

	condition_option = OptionButton.new()
	condition_option.custom_minimum_size = Vector2(270, 0)
	condition_option.add_item("Baseline: all modalities")
	condition_option.add_item("Condition A: no audio")
	condition_option.add_item("Condition B: no gestures")
	condition_option.add_item("Condition C: no objects")
	condition_option.add_item("Condition D: no sand surface")
	condition_option.add_item("Stage 2: annotations + links")
	condition_option.item_selected.connect(_on_condition_selected)
	_style_button(condition_option, "toolbar")
	top_row.add_child(condition_option)

	focus_button = Button.new()
	focus_button.text = "Focus 3D"
	focus_button.custom_minimum_size = Vector2(110, 0)
	focus_button.pressed.connect(_toggle_focus_mode)
	_style_button(focus_button, "primary")
	top_row.add_child(focus_button)

	reference_views_button = Button.new()
	reference_views_button.text = "Reference views"
	reference_views_button.custom_minimum_size = Vector2(150, 0)
	reference_views_button.pressed.connect(_toggle_reference_views)
	_style_button(reference_views_button, "toolbar")
	top_row.add_child(reference_views_button)

	source_status_label = Label.new()
	source_status_label.text = "Surface source: pending"
	source_status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	source_status_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_apply_text_style(source_status_label, ui_font_strong, 14)
	source_status_label.add_theme_color_override("font_color", Color(0.83, 0.87, 0.8))
	top_row.add_child(source_status_label)

	var panel := PanelContainer.new()
	panel.name = "ModalityRail"
	modality_panel = panel
	panel.add_theme_stylebox_override("panel", _panel_style(Color(0.045, 0.054, 0.05, 0.94), 14))
	panel.anchor_left = 0.0
	panel.anchor_top = 0.0
	panel.anchor_right = 0.0
	panel.anchor_bottom = 1.0
	panel.offset_left = 16
	panel.offset_top = 86
	panel.offset_right = 336
	panel.offset_bottom = -118
	hud_root.add_child(panel)

	var rail_scroll := ScrollContainer.new()
	rail_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	rail_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rail_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	panel.add_child(rail_scroll)

	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 8)
	root.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rail_scroll.add_child(root)

	var section_title := Label.new()
	section_title.text = "Layer Console"
	_apply_text_style(section_title, ui_font_display, 20)
	section_title.add_theme_color_override("font_color", Color(0.93, 0.91, 0.82))
	root.add_child(section_title)

	_add_layer_toggle(root, "sand", "RGB-D sand surface", true)
	_add_layer_toggle(root, "heightmap_surface", "Use reconstructed depth map", true)
	_add_layer_toggle(root, "gestures", "Virtual hand / gestures", true)
	_add_layer_toggle(root, "objects", "Objects / tools", true)
	_add_layer_toggle(root, "annotations", "Annotations + links", false)

	var source_title := Label.new()
	source_title.text = "Input Streams"
	_apply_text_style(source_title, ui_font_strong, 17)
	source_title.add_theme_color_override("font_color", Color(0.58, 0.72, 0.69))
	root.add_child(source_title)

	video_stream_toggle = CheckBox.new()
	video_stream_toggle.text = "Synced OGV depth/material"
	video_stream_toggle.button_pressed = use_video_streams
	video_stream_toggle.toggled.connect(func(value: bool) -> void:
		use_video_streams = value
		_apply_surface_texture_source()
		_update_source_status()
		_log_event("surface_source_toggle", {"use_video_streams": use_video_streams})
	)
	_style_checkbox(video_stream_toggle)
	root.add_child(video_stream_toggle)

	var reset_button := Button.new()
	reset_button.text = "Reset camera (R)"
	reset_button.pressed.connect(func() -> void: _set_camera_preset("orbit"))
	_style_button(reset_button, "secondary")
	root.add_child(reset_button)

	active_event_label = Label.new()
	active_event_label.text = "Active gesture: none"
	active_event_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_apply_text_style(active_event_label, ui_font_strong, 15)
	active_event_label.add_theme_color_override("font_color", Color(0.95, 0.74, 0.48))
	root.add_child(active_event_label)

	hand_status_label = Label.new()
	hand_status_label.text = "Hand tracks: pending"
	hand_status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_apply_text_style(hand_status_label, ui_font_strong, 14)
	hand_status_label.add_theme_color_override("font_color", Color(0.63, 0.77, 0.74))
	root.add_child(hand_status_label)

	var calibration := VBoxContainer.new()
	calibration.name = "Calibration"
	calibration.add_theme_constant_override("separation", 5)
	root.add_child(calibration)

	var surface_label := Label.new()
	surface_label.text = "Depth / Material Fit"
	_apply_text_style(surface_label, ui_font_strong, 17)
	surface_label.add_theme_color_override("font_color", Color(0.58, 0.72, 0.69))
	calibration.add_child(surface_label)

	_add_surface_slider(calibration, "depth_u", "Depth U", -1.0, 1.0, 0.001, 0.0)
	_add_surface_slider(calibration, "depth_v", "Depth V", -1.0, 1.0, 0.001, 0.0)
	_add_surface_slider(calibration, "texture_u", "Texture U", -1.0, 1.0, 0.001, 0.0)
	_add_surface_slider(calibration, "texture_v", "Texture V", -1.0, 1.0, 0.001, 0.0)
	_add_surface_slider(calibration, "displacement", "Height", 0.0, 3.0, 0.01, 1.0)
	_add_surface_slider(calibration, "material_strength", "Map blend", 0.0, 1.0, 0.01, 0.0)
	_add_surface_frame_controls(calibration)

	var hint := Label.new()
	hint.text = "Camera: WASD glide, Shift boost, drag orbit, wheel/Q/E zoom, 1 top, 2 front, 3 orbit."
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_apply_text_style(hint, ui_font, 13)
	hint.add_theme_color_override("font_color", Color(0.76, 0.8, 0.75))
	root.add_child(hint)

	_build_study_panel(hud_root)
	if DisplayServer.get_name() != "headless":
		_build_fixed_views(hud_root)

	lower_dock_panel = Panel.new()
	lower_dock_panel.name = "LowerViewportMask"
	lower_dock_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	lower_dock_panel.add_theme_stylebox_override("panel", _panel_style(Color(0.045, 0.054, 0.05, 0.94), 14))
	lower_dock_panel.anchor_left = 0.0
	lower_dock_panel.anchor_top = 1.0
	lower_dock_panel.anchor_right = 1.0
	lower_dock_panel.anchor_bottom = 1.0
	lower_dock_panel.offset_left = 352
	lower_dock_panel.offset_top = -254
	lower_dock_panel.offset_right = -430
	lower_dock_panel.offset_bottom = -16
	hud_root.add_child(lower_dock_panel)

	var lower_hint := Label.new()
	lower_hint.text = "Viewport dock: split hand meshes + MediaPipe 21pt skeletons are live. Focus 3D opens the full reconstruction."
	lower_hint.modulate = Color(0.78, 0.84, 0.8, 0.72)
	_apply_text_style(lower_hint, ui_font_strong, 14)
	lower_hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	lower_hint.mouse_filter = Control.MOUSE_FILTER_IGNORE
	lower_hint.anchor_left = 0.0
	lower_hint.anchor_top = 0.0
	lower_hint.anchor_right = 1.0
	lower_hint.anchor_bottom = 0.0
	lower_hint.offset_left = 18
	lower_hint.offset_top = 14
	lower_hint.offset_right = -18
	lower_hint.offset_bottom = 54
	lower_dock_panel.add_child(lower_hint)

	var transport_bar := PanelContainer.new()
	transport_bar.name = "TransportBar"
	transport_bar.add_theme_stylebox_override("panel", _panel_style(Color(0.045, 0.054, 0.05, 0.96), 14))
	transport_bar.anchor_left = 0.0
	transport_bar.anchor_top = 1.0
	transport_bar.anchor_right = 1.0
	transport_bar.anchor_bottom = 1.0
	transport_bar.offset_left = 16
	transport_bar.offset_top = -102
	transport_bar.offset_right = -16
	transport_bar.offset_bottom = -16
	hud_root.add_child(transport_bar)

	var transport := HBoxContainer.new()
	transport.add_theme_constant_override("separation", 10)
	transport_bar.add_child(transport)

	play_button = Button.new()
	play_button.text = "Play"
	play_button.custom_minimum_size = Vector2(92, 0)
	play_button.pressed.connect(_on_play_pressed)
	_style_button(play_button, "primary")
	transport.add_child(play_button)

	time_label = Label.new()
	time_label.text = "0.00 / 0.00"
	time_label.custom_minimum_size = Vector2(120, 0)
	_apply_text_style(time_label, ui_font_strong, 15)
	time_label.add_theme_color_override("font_color", Color(0.93, 0.91, 0.82))
	transport.add_child(time_label)

	time_slider = HSlider.new()
	time_slider.min_value = 0.0
	time_slider.max_value = 1.0
	time_slider.step = 0.01
	time_slider.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	time_slider.value_changed.connect(_on_time_changed)
	transport.add_child(time_slider)


func _build_study_panel(canvas: Control) -> void:
	var panel := PanelContainer.new()
	panel.name = "StudyPanel"
	study_panel = panel
	panel.add_theme_stylebox_override("panel", _panel_style(Color(0.045, 0.054, 0.05, 0.94), 14))
	panel.anchor_left = 1.0
	panel.anchor_top = 0.0
	panel.anchor_right = 1.0
	panel.anchor_bottom = 1.0
	panel.offset_left = -430
	panel.offset_top = 86
	panel.offset_right = -16
	panel.offset_bottom = -118
	canvas.add_child(panel)

	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	panel.add_child(scroll)

	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 10)
	root.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(root)

	var title := Label.new()
	title.text = "Study Inspector"
	_apply_text_style(title, ui_font_display, 21)
	title.add_theme_color_override("font_color", Color(0.93, 0.91, 0.82))
	root.add_child(title)

	task_label = Label.new()
	task_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	task_label.text = "Tasks will load from session.json."
	_apply_text_style(task_label, ui_font, 15)
	task_label.add_theme_color_override("font_color", Color(0.86, 0.88, 0.82))
	root.add_child(task_label)

	participant_label = Label.new()
	participant_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	participant_label.visible = false
	_apply_text_style(participant_label, ui_font_strong, 14)
	participant_label.add_theme_color_override("font_color", Color(0.63, 0.77, 0.74))
	root.add_child(participant_label)

	var capture_button := Button.new()
	capture_button.text = "Mark current view as evidence"
	capture_button.pressed.connect(_on_mark_evidence_pressed)
	_style_button(capture_button, "secondary")
	root.add_child(capture_button)

	evidence_label = Label.new()
	evidence_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	evidence_label.text = "No evidence marked yet."
	_apply_text_style(evidence_label, ui_font, 15)
	evidence_label.add_theme_color_override("font_color", Color(0.78, 0.84, 0.78))
	root.add_child(evidence_label)

	response_notes = TextEdit.new()
	response_notes.placeholder_text = "Participant summary / answer evidence notes"
	response_notes.custom_minimum_size = Vector2(0, 170)
	response_notes.add_theme_stylebox_override("normal", _panel_style(Color(0.025, 0.03, 0.028, 0.96), 10))
	_apply_text_style(response_notes, ui_font, 15)
	response_notes.add_theme_color_override("font_color", Color(0.9, 0.9, 0.82))
	response_notes.add_theme_color_override("font_placeholder_color", Color(0.58, 0.63, 0.58))
	root.add_child(response_notes)

	var submit_button := Button.new()
	submit_button.text = "Log response draft"
	submit_button.pressed.connect(_on_log_response_pressed)
	_style_button(submit_button, "primary")
	root.add_child(submit_button)


func _build_fixed_views(canvas: Control) -> void:
	var views_panel := PanelContainer.new()
	views_panel.name = "FixedViewsPanel"
	fixed_views_panel = views_panel
	views_panel.add_theme_stylebox_override("panel", _panel_style(Color(0.045, 0.054, 0.05, 0.95), 14))
	views_panel.visible = reference_views_visible
	views_panel.anchor_left = 1.0
	views_panel.anchor_top = 1.0
	views_panel.anchor_right = 1.0
	views_panel.anchor_bottom = 1.0
	views_panel.offset_left = -650
	views_panel.offset_top = -344
	views_panel.offset_right = -16
	views_panel.offset_bottom = -118
	canvas.add_child(views_panel)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	views_panel.add_child(row)

	top_viewport = _make_viewport_camera("TopView", Vector3(0, 6.5, 0.01), Vector3.ZERO)
	front_viewport = _make_viewport_camera("FrontView", Vector3(0, 2.4, 6.5), Vector3(0, 0.05, 0))
	top_view_camera = top_viewport.get_node("TopViewCamera")
	front_view_camera = front_viewport.get_node("FrontViewCamera")

	_add_view_texture(row, "Top-down RGB/depth proxy", top_viewport)
	_add_view_texture(row, "Front-view proxy", front_viewport)


func _make_viewport_camera(view_name: String, camera_position: Vector3, target: Vector3) -> SubViewport:
	var viewport := SubViewport.new()
	viewport.name = view_name
	viewport.size = Vector2i(300, 210)
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.transparent_bg = false
	viewport.world_3d = get_world_3d()
	add_child(viewport)

	var view_camera := Camera3D.new()
	view_camera.name = view_name + "Camera"
	view_camera.fov = 42
	viewport.add_child(view_camera)
	var direction := (target - camera_position).normalized()
	var up := Vector3.FORWARD if abs(direction.dot(Vector3.UP)) > 0.95 else Vector3.UP
	view_camera.look_at_from_position(camera_position, target, up)
	viewport.camera_3d = view_camera
	return viewport


func _add_view_texture(parent: Control, label: String, viewport: SubViewport) -> void:
	var box := VBoxContainer.new()
	parent.add_child(box)

	var label_node := Label.new()
	label_node.text = label
	_apply_text_style(label_node, ui_font_strong, 14)
	label_node.add_theme_color_override("font_color", Color(0.83, 0.87, 0.8))
	box.add_child(label_node)

	var texture_rect := TextureRect.new()
	texture_rect.texture = viewport.get_texture()
	texture_rect.custom_minimum_size = Vector2(300, 210)
	texture_rect.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	box.add_child(texture_rect)


func _add_layer_toggle(parent: Control, key: String, label: String, enabled: bool) -> void:
	var toggle := CheckBox.new()
	toggle.text = label
	toggle.button_pressed = enabled
	toggle.toggled.connect(func(value: bool) -> void:
		_set_layer_visible(key, value)
		_log_event("layer_toggle", {"layer": key, "visible": value})
	)
	_style_checkbox(toggle)
	layer_toggles[key] = toggle
	parent.add_child(toggle)


func _add_surface_slider(parent: Control, key: String, label: String, min_value: float, max_value: float, step: float, initial_value: float) -> void:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	parent.add_child(row)

	var label_node := Label.new()
	label_node.text = label
	label_node.custom_minimum_size = Vector2(76, 0)
	_apply_text_style(label_node, ui_font_strong, 14)
	label_node.add_theme_color_override("font_color", Color(0.82, 0.86, 0.78))
	row.add_child(label_node)

	var slider := HSlider.new()
	slider.min_value = min_value
	slider.max_value = max_value
	slider.step = step
	slider.value = initial_value
	slider.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	slider.value_changed.connect(func(value: float) -> void:
		surface_controls[key] = value
		_apply_surface_controls()
		_log_event("surface_control", {"key": key, "value": value})
	)
	surface_sliders[key] = slider
	row.add_child(slider)


func _add_surface_frame_controls(parent: Control) -> void:
	var title := Label.new()
	title.text = "Production Frame"
	_apply_text_style(title, ui_font_strong, 15)
	title.add_theme_color_override("font_color", Color(0.82, 0.86, 0.78))
	parent.add_child(title)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 8)
	parent.add_child(row)

	var prev_button := Button.new()
	prev_button.text = "<"
	prev_button.custom_minimum_size = Vector2(34, 0)
	prev_button.pressed.connect(func() -> void:
		_set_surface_frame(surface_frame_index - 1)
	)
	_style_button(prev_button, "secondary")
	row.add_child(prev_button)

	surface_frame_slider = HSlider.new()
	surface_frame_slider.min_value = 1
	surface_frame_slider.max_value = 1
	surface_frame_slider.step = 1
	surface_frame_slider.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	surface_frame_slider.value_changed.connect(func(value: float) -> void:
		_set_surface_frame(int(round(value)) - 1)
	)
	row.add_child(surface_frame_slider)

	var next_button := Button.new()
	next_button.text = ">"
	next_button.custom_minimum_size = Vector2(34, 0)
	next_button.pressed.connect(func() -> void:
		_set_surface_frame(surface_frame_index + 1)
	)
	_style_button(next_button, "secondary")
	row.add_child(next_button)

	surface_frame_label = Label.new()
	surface_frame_label.text = "No processed frames"
	surface_frame_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_apply_text_style(surface_frame_label, ui_font, 13)
	surface_frame_label.add_theme_color_override("font_color", Color(0.76, 0.8, 0.75))
	parent.add_child(surface_frame_label)


func _load_session(path: String) -> void:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("Cannot open session file: " + path)
		return

	var parsed = JSON.parse_string(file.get_as_text())
	if typeof(parsed) != TYPE_DICTIONARY:
		push_error("Invalid session JSON: " + path)
		return

	session = parsed
	data_sources = session.get("data_sources", {})
	_load_processed_surface_frames()
	use_video_streams = bool(data_sources.get("use_video_streams", false))
	_apply_session_calibration_defaults()
	if video_stream_toggle != null:
		video_stream_toggle.set_pressed_no_signal(use_video_streams)
	duration = float(session.get("duration", 1.0))
	time_slider.max_value = duration
	_build_session_nodes()
	_update_source_status()
	_log_event("session_loaded", {"path": path, "duration": duration})


func _load_processed_surface_frames() -> void:
	processed_surface_frames.clear()
	processed_surface_base_dir = ""
	surface_frame_index = -1

	var manifest_path := str(data_sources.get("processed_manifest", ""))
	if manifest_path == "" or not FileAccess.file_exists(manifest_path):
		_update_surface_frame_ui()
		return

	var file := FileAccess.open(manifest_path, FileAccess.READ)
	if file == null:
		_update_surface_frame_ui()
		return
	var parsed = JSON.parse_string(file.get_as_text())
	if typeof(parsed) != TYPE_DICTIONARY:
		_update_surface_frame_ui()
		return

	processed_surface_base_dir = manifest_path.get_base_dir()
	var frames: Array = parsed.get("frames", [])
	for frame in frames:
		if typeof(frame) != TYPE_DICTIONARY:
			continue
		if not frame.has("cleanDepth") or not frame.has("cleanRgb"):
			continue
		processed_surface_frames.append(frame)

	if processed_surface_frames.is_empty():
		_update_surface_frame_ui()
		return

	var selected := processed_surface_frames.size() - 1
	var current_depth := str(data_sources.get("depth_map", ""))
	for index in range(processed_surface_frames.size()):
		var frame: Dictionary = processed_surface_frames[index]
		if _surface_frame_path(frame, "cleanDepth") == current_depth:
			selected = index
			break
	_set_surface_frame(selected, false)


func _surface_frame_path(frame: Dictionary, key: String) -> String:
	var value := str(frame.get(key, ""))
	if value == "":
		return ""
	if value.begins_with("res://") or value.begins_with("user://"):
		return value
	if processed_surface_base_dir == "":
		return value
	return processed_surface_base_dir.path_join(value)


func _set_surface_frame(index: int, apply_now := true) -> void:
	if processed_surface_frames.is_empty():
		surface_frame_index = -1
		_update_surface_frame_ui()
		return
	surface_frame_index = clamp(index, 0, processed_surface_frames.size() - 1)
	var frame: Dictionary = processed_surface_frames[surface_frame_index]
	var depth_key := "detailDepth" if frame.has("detailDepth") else "cleanDepth"
	var depth_path := _surface_frame_path(frame, depth_key)
	var texture_path := _surface_frame_path(frame, "cleanRgb")
	var occlusion_path := _surface_frame_path(frame, "occlusionMask")
	var overlay_path := _surface_frame_path(frame, "maskOverlay")
	if depth_path != "":
		data_sources["depth_map"] = depth_path
	if texture_path != "":
		data_sources["texture_map"] = texture_path
	if occlusion_path != "":
		data_sources["occlusion_mask"] = occlusion_path
	if overlay_path != "":
		data_sources["mask_overlay"] = overlay_path
	if apply_now:
		_reload_static_surface_textures()
		_apply_surface_texture_source()
		_update_source_status()
		_log_event("surface_frame_selected", {
			"index": surface_frame_index + 1,
			"frameIndex": frame.get("frameIndex", surface_frame_index + 1),
			"time": frame.get("time", 0.0)
		})
	_update_surface_frame_ui()


func _update_surface_frame_ui() -> void:
	if surface_frame_slider != null:
		var count: int = max(1, processed_surface_frames.size())
		surface_frame_slider.max_value = count
		surface_frame_slider.editable = processed_surface_frames.size() > 1
		surface_frame_slider.set_value_no_signal(max(1, surface_frame_index + 1))
	if surface_frame_label == null:
		return
	if processed_surface_frames.is_empty() or surface_frame_index < 0:
		surface_frame_label.text = "No processed frames loaded."
		return
	var frame: Dictionary = processed_surface_frames[surface_frame_index]
	surface_frame_label.text = "Frame %d/%d | capture #%s | %.2fs | mask %d px" % [
		surface_frame_index + 1,
		processed_surface_frames.size(),
		str(frame.get("frameIndex", surface_frame_index + 1)),
		float(frame.get("time", 0.0)),
		int(frame.get("occlusionPixels", 0))
	]


func _apply_session_calibration_defaults() -> void:
	var calibration: Dictionary = data_sources.get("calibration", {})
	var depth_offset := _array_to_vec2(calibration.get("depth_uv_offset", [surface_controls["depth_u"], surface_controls["depth_v"]]))
	var texture_offset := _array_to_vec2(calibration.get("texture_uv_offset", [surface_controls["texture_u"], surface_controls["texture_v"]]))
	surface_controls["depth_u"] = depth_offset.x
	surface_controls["depth_v"] = depth_offset.y
	surface_controls["texture_u"] = texture_offset.x
	surface_controls["texture_v"] = texture_offset.y
	surface_controls["displacement"] = float(calibration.get("height_scale", surface_controls["displacement"]))
	surface_controls["material_strength"] = float(calibration.get("material_strength", surface_controls["material_strength"]))
	for key in surface_controls.keys():
		if surface_sliders.has(key):
			surface_sliders[key].set_value_no_signal(float(surface_controls[key]))


func _apply_launch_params() -> void:
	if not OS.has_feature("web"):
		return
	var query_json: Variant = JavaScriptBridge.eval("JSON.stringify(Object.fromEntries(new URLSearchParams(location.search)))")
	var query: Variant = JSON.parse_string(str(query_json))
	if typeof(query) != TYPE_DICTIONARY:
		return
	if query.has("session"):
		var requested_session := str(query["session"])
		if requested_session != "":
			_load_session(requested_session)
	if query.has("condition"):
		var requested := str(query["condition"])
		var condition_map := {
			"baseline": 0,
			"no_audio": 1,
			"no_gestures": 2,
			"no_objects": 3,
			"no_sand": 4,
			"stage2": 5
		}
		if condition_map.has(requested):
			current_condition = requested
			if condition_option != null:
				condition_option.select(int(condition_map[requested]))
	if query.has("video"):
		use_video_streams = str(query["video"]) in ["1", "true", "yes"]
		if video_stream_toggle != null:
			video_stream_toggle.set_pressed_no_signal(use_video_streams)
		_apply_surface_texture_source()
	if query.has("view"):
		_set_camera_preset(str(query["view"]))
	if query.has("unicode"):
		unicode_smoke_test_enabled = str(query["unicode"]).to_lower() in ["1", "true", "yes"]
	if unicode_smoke_test_enabled:
		_apply_unicode_smoke_test()


func _apply_unicode_smoke_test() -> void:
	var names := [
		"张伟", "王芳", "李娜", "陈晨", "刘洋", "黄静", "赵敏", "吴磊",
		"周雨欣", "徐子涵", "孙浩然", "马思远", "朱一鸣", "胡嘉怡", "郭明轩", "何雨桐",
		"高梓萱", "林子墨", "罗欣怡", "梁宇航", "宋佳宁", "郑雅婷", "谢晨曦", "韩若曦",
		"唐嘉豪", "冯语嫣", "于昊天", "董思琪", "萧逸凡", "曹婉婷", "袁博文", "邓雨菲",
		"许家豪", "曾可欣", "潘子轩", "彭诗涵", "蔡明哲", "姚思源", "阿依古丽", "卓玛"
	]
	session["title"] = "Unicode/CJK Smoke Test：中文姓名、标注与日志"
	var participants := []
	for index in range(names.size()):
		participants.append({
			"id": "p%02d" % [index + 1],
			"display_name": names[index],
			"role": "participant"
		})
	session["participants"] = participants
	var sample_names := PackedStringArray()
	for index in range(min(12, names.size())):
		sample_names.append(names[index])
	session["study_tasks"] = [
		{
			"id": "unicode_roster",
			"prompt": "确认中文姓名、中文标点、顿号和换行显示正常：%s" % "、".join(sample_names)
		},
		{
			"id": "unicode_response",
			"prompt": "在 response notes 中输入中文句子，点击 Log response draft，检查日志是否保留 UTF-8。"
		}
	]
	var annotations: Array = session.get("annotations", [])
	if annotations.size() > 0:
		annotations[0]["label"] = "河道：张伟的路线"
	if annotations.size() > 1:
		annotations[1]["label"] = "营地：王芳的解释"
	session["annotations"] = annotations
	var objects: Array = session.get("objects", [])
	if objects.size() > 0:
		objects[0]["label"] = "水源道具"
	if objects.size() > 1:
		objects[1]["label"] = "营地模型"
	session["objects"] = objects
	_build_session_nodes()
	_update_participant_text()
	_log_event("unicode_smoke_test", {
		"names": names,
		"sample": "中文姓名测试：张伟、王芳、李娜、陈晨"
	})


func _build_session_nodes() -> void:
	_clear_children(sand_layer)
	_clear_children(gesture_layer)
	_clear_children(object_layer)
	_clear_children(annotation_layer)
	hand_tracks = _session_hand_tracks()
	hand_track_roots.clear()
	hand_model_nodes.clear()
	hand_joint_nodes.clear()
	hand_bone_nodes.clear()
	hand_virtual_nodes.clear()
	hand_rendered_points.clear()
	object_nodes.clear()
	annotation_nodes.clear()
	highlight_nodes.clear()
	relation_nodes.clear()
	object_nodes_by_id.clear()
	annotation_nodes_by_id.clear()
	highlight_layer = Node3D.new()
	highlight_layer.name = "SandHighlightLayer"
	annotation_layer.add_child(highlight_layer)
	relation_layer = Node3D.new()
	relation_layer.name = "ReferentialRelationLayer"
	annotation_layer.add_child(relation_layer)

	sand_mesh_instance = MeshInstance3D.new()
	sand_mesh_instance.name = "SandSurface"
	sand_mesh_instance.mesh = _make_sand_mesh()
	sand_mesh_instance.material_override = _sand_material()
	sand_layer.add_child(sand_mesh_instance)
	_build_heightmap_surface()

	_build_hand_tracks()
	_update_hand_status()

	for object_data in session.get("objects", []):
		var object_node := MeshInstance3D.new()
		object_node.name = str(object_data.get("id", "Object"))
		object_node.mesh = _object_mesh_from_data(object_data)
		object_node.material_override = _material(_color_from_hex(str(object_data.get("color", "#7b4f31"))), 1.0)
		object_node.position = _array_to_vec3(object_data.get("position", [0, 0.15, 0]))
		object_layer.add_child(object_node)
		object_nodes.append(object_node)
		object_nodes_by_id[str(object_data.get("id", "Object"))] = object_node

	for annotation_data in session.get("annotations", []):
		var marker := Label3D.new()
		marker.name = str(annotation_data.get("id", "Annotation"))
		marker.text = str(annotation_data.get("label", "Annotation"))
		marker.billboard = BaseMaterial3D.BILLBOARD_ENABLED
		marker.font_size = 42
		if ui_font_strong != null:
			marker.font = ui_font_strong
		marker.modulate = _color_from_hex(str(annotation_data.get("color", "#176f8a")))
		marker.position = _array_to_vec3(annotation_data.get("position", [0, 0.45, 0]))
		annotation_layer.add_child(marker)
		annotation_nodes.append(marker)
		annotation_nodes_by_id[str(annotation_data.get("id", "Annotation"))] = marker

	_build_surface_highlights()
	_build_referential_links()
	_update_task_text()


func _object_mesh_from_data(object_data: Dictionary) -> Mesh:
	var model_path := str(object_data.get("model_path", ""))
	if model_path != "" and ResourceLoader.exists(model_path):
		var resource := load(model_path)
		if resource is Mesh:
			return resource

	var primitive := str(object_data.get("primitive", "box"))
	var size := _array_to_vec3(object_data.get("size", [0.4, 0.25, 0.4]))
	match primitive:
		"sphere":
			var sphere := SphereMesh.new()
			sphere.radius = max(size.x, size.z) * 0.5
			sphere.height = max(size.y, sphere.radius * 2.0)
			return sphere
		"cylinder":
			var cylinder := CylinderMesh.new()
			cylinder.top_radius = max(size.x, size.z) * 0.5
			cylinder.bottom_radius = cylinder.top_radius
			cylinder.height = size.y
			return cylinder
		_:
			var box := BoxMesh.new()
			box.size = size
			return box


func _session_hand_tracks() -> Array:
	if session.has("hand_tracks"):
		return session.get("hand_tracks", [])
	if session.has("mediapipe_hands"):
		return _tracks_from_mediapipe_frames(session.get("mediapipe_hands", []))
	var samples: Array = session.get("hand_samples", [])
	if samples.is_empty():
		return []
	return [{
		"id": "right_hand",
		"label": "Right hand",
		"handedness": "right",
		"model_path": HAND_MODEL_RIGHT_PATH,
		"color": "#5ec8d8",
		"joint_count": int(session.get("hand_joint_count", 5)),
		"samples": samples
	}]


func _tracks_from_mediapipe_frames(frames: Array) -> Array:
	var by_id := {}
	for frame in frames:
		if typeof(frame) != TYPE_DICTIONARY:
			continue
		var time := float(frame.get("time", 0.0))
		for hand in frame.get("hands", []):
			if typeof(hand) != TYPE_DICTIONARY:
				continue
			var handedness := str(hand.get("handedness", hand.get("label", "hand"))).to_lower()
			var id := str(hand.get("id", "%s_hand" % handedness))
			if not by_id.has(id):
				by_id[id] = {
					"id": id,
					"label": str(hand.get("label", handedness.capitalize() + " hand")),
					"handedness": handedness,
					"model_path": HAND_MODEL_LEFT_PATH if handedness == "left" else HAND_MODEL_RIGHT_PATH,
					"color": str(hand.get("color", "#5ec8d8" if handedness == "right" else "#f1a85b")),
					"joint_count": 21,
					"samples": []
				}
			by_id[id]["samples"].append({
				"time": time,
				"landmarks": hand.get("landmarks", hand.get("joints", []))
			})
	return by_id.values()


func _build_hand_tracks() -> void:
	for track in hand_tracks:
		if typeof(track) != TYPE_DICTIONARY:
			continue
		var track_id := str(track.get("id", "hand"))
		var root := Node3D.new()
		root.name = "HandTrack_" + track_id
		gesture_layer.add_child(root)
		hand_track_roots[track_id] = root

		var color := _color_from_hex(str(track.get("color", "#5ec8d8")))
		if bool(track.get("virtual_hand", true)):
			_build_virtual_hand_for_track(root, track_id, color)

		var model := _build_hand_model_for_track(track)
		if model != null:
			root.add_child(model)
			hand_model_nodes[track_id] = model

		var joint_count := int(track.get("joint_count", _track_joint_count(track)))
		var joints: Array[MeshInstance3D] = []
		for joint_index in range(joint_count):
			var joint := MeshInstance3D.new()
			joint.name = "%s_Landmark%d" % [track_id, joint_index]
			var sphere := SphereMesh.new()
			sphere.radius = _hand_joint_radius(joint_index, joint_count)
			sphere.height = sphere.radius * 2.0
			sphere.radial_segments = 12
			sphere.rings = 6
			joint.mesh = sphere
			joint.material_override = _hand_joint_material(color, joint_index, joint_count)
			root.add_child(joint)
			joints.append(joint)
		hand_joint_nodes[track_id] = joints

		var bones: Array[MeshInstance3D] = []
		for bone_index in range(MEDIAPIPE_HAND_BONES.size()):
			var bone := MeshInstance3D.new()
			bone.name = "%s_Bone%d" % [track_id, bone_index]
			var cylinder := CylinderMesh.new()
			cylinder.height = 1.0
			cylinder.top_radius = _hand_bone_radius(bone_index)
			cylinder.bottom_radius = cylinder.top_radius
			cylinder.radial_segments = 8
			cylinder.rings = 1
			bone.mesh = cylinder
			bone.material_override = _hand_bone_material(color, bone_index)
			root.add_child(bone)
			bones.append(bone)
		hand_bone_nodes[track_id] = bones
		hand_rendered_points[track_id] = []


func _build_hand_model_for_track(track: Dictionary) -> MeshInstance3D:
	var fallback := HAND_MODEL_LEFT_PATH if str(track.get("handedness", "")).to_lower() == "left" else HAND_MODEL_RIGHT_PATH
	var model_path := str(track.get("model_path", fallback))
	if model_path == "" or not ResourceLoader.exists(model_path):
		return null
	var mesh := load(model_path)
	if mesh == null or not mesh is Mesh:
		return null

	var model := MeshInstance3D.new()
	model.name = "MeshGhost_" + str(track.get("id", "hand"))
	model.mesh = mesh
	model.scale = Vector3.ONE * float(track.get("model_scale", 0.72))
	model.rotation_degrees = _array_to_vec3(track.get("model_rotation_degrees", [-90.0, 20.0, 0.0]))
	var color := _color_from_hex(str(track.get("mesh_color", track.get("color", "#5ec8d8"))))
	model.material_override = _ghost_material(color)
	model.visible = false
	return model


func _build_virtual_hand_for_track(root: Node3D, track_id: String, color: Color) -> void:
	var virtual_root := Node3D.new()
	virtual_root.name = "HologramHand_" + track_id
	root.add_child(virtual_root)

	var palm := MeshInstance3D.new()
	palm.name = track_id + "_PalmShell"
	palm.material_override = _hologram_material(color, 0.28, 1.0)
	virtual_root.add_child(palm)

	var segments: Array[MeshInstance3D] = []
	for segment_index in range(VIRTUAL_HAND_SEGMENTS.size()):
		var segment := MeshInstance3D.new()
		segment.name = "%s_HologramSegment%d" % [track_id, segment_index]
		var cylinder := CylinderMesh.new()
		cylinder.height = 1.0
		cylinder.top_radius = _virtual_segment_radius(segment_index)
		cylinder.bottom_radius = cylinder.top_radius
		cylinder.radial_segments = 12
		cylinder.rings = 2
		segment.mesh = cylinder
		segment.material_override = _hologram_material(color, 0.36, float(segment_index) * 0.07)
		virtual_root.add_child(segment)
		segments.append(segment)

	var tips: Array[MeshInstance3D] = []
	for tip_index in range(VIRTUAL_HAND_TIPS.size()):
		var tip := MeshInstance3D.new()
		tip.name = "%s_HologramTip%d" % [track_id, tip_index]
		var sphere := SphereMesh.new()
		sphere.radius = 0.062
		sphere.height = 0.124
		sphere.radial_segments = 16
		sphere.rings = 8
		tip.mesh = sphere
		tip.material_override = _hologram_material(color.lightened(0.18), 0.48, 0.5 + float(tip_index) * 0.11)
		virtual_root.add_child(tip)
		tips.append(tip)

	hand_virtual_nodes[track_id] = {
		"root": virtual_root,
		"palm": palm,
		"segments": segments,
		"tips": tips
	}


func _virtual_segment_radius(segment_index: int) -> float:
	if segment_index >= VIRTUAL_HAND_SEGMENTS.size():
		return 0.03
	var connection: Array = VIRTUAL_HAND_SEGMENTS[segment_index]
	var a := int(connection[0])
	var b := int(connection[1])
	if a == 0:
		return 0.055
	if b in VIRTUAL_HAND_TIPS:
		return 0.032
	if a in [5, 9, 13, 17]:
		return 0.046
	return 0.038


func _hologram_material(color: Color, alpha: float, pulse_offset: float) -> Material:
	if ResourceLoader.exists(HAND_HOLOGRAM_SHADER_PATH):
		var shader := load(HAND_HOLOGRAM_SHADER_PATH)
		if shader is Shader:
			var material := ShaderMaterial.new()
			material.shader = shader
			material.set_shader_parameter("core_color", Color(color.r, color.g, color.b, alpha))
			material.set_shader_parameter("alpha", alpha)
			material.set_shader_parameter("pulse_speed", 0.72 + pulse_offset * 0.08)
			material.set_shader_parameter("scanline_strength", 0.14)
			return material

	var fallback := StandardMaterial3D.new()
	fallback.albedo_color = Color(color.r, color.g, color.b, alpha)
	fallback.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	fallback.emission_enabled = true
	fallback.emission = color.lightened(0.2)
	fallback.emission_energy_multiplier = 0.2
	fallback.roughness = 0.24
	return fallback


func _hand_joint_radius(index: int, joint_count: int) -> float:
	if joint_count < 21:
		return 0.07
	if index == 0:
		return 0.052
	if index in [4, 8, 12, 16, 20]:
		return 0.047
	if index in [5, 9, 13, 17]:
		return 0.043
	return 0.036


func _hand_bone_radius(bone_index: int) -> float:
	if bone_index >= MEDIAPIPE_HAND_BONES.size():
		return 0.013
	var connection: Array = MEDIAPIPE_HAND_BONES[bone_index]
	var a := int(connection[0])
	var b := int(connection[1])
	if a == 0 or b == 0:
		return 0.018
	if bone_index >= 20:
		return 0.012
	return 0.014


func _hand_joint_material(color: Color, index: int, joint_count: int) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	var tip_boost := 0.18 if joint_count >= 21 and index in [4, 8, 12, 16, 20] else 0.0
	var albedo := color.lightened(0.16 + tip_boost)
	material.albedo_color = albedo
	material.roughness = 0.48
	material.emission_enabled = true
	material.emission = color.lightened(0.28 + tip_boost)
	material.emission_energy_multiplier = 0.18
	return material


func _hand_bone_material(color: Color, bone_index: int) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	var alpha := 0.78 if bone_index < 20 else 0.42
	material.albedo_color = Color(color.r, color.g, color.b, alpha)
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	material.roughness = 0.62
	material.emission_enabled = true
	material.emission = color.lightened(0.18)
	material.emission_energy_multiplier = 0.08
	return material


func _track_joint_count(track: Dictionary) -> int:
	var samples: Array = track.get("samples", [])
	for sample in samples:
		if typeof(sample) != TYPE_DICTIONARY:
			continue
		var joints: Array = sample.get("landmarks", sample.get("joints", []))
		if not joints.is_empty():
			return joints.size()
	return 21


func _build_heightmap_surface() -> void:
	var material := _heightmap_material()
	if material == null:
		_update_source_status("RGB-D material unavailable; using procedural fallback.")
		return
	heightmap_material = material

	var plane := PlaneMesh.new()
	plane.size = Vector2(5.5, 5.5)
	plane.subdivide_width = 256
	plane.subdivide_depth = 256

	heightmap_surface_node = MeshInstance3D.new()
	heightmap_surface_node.name = "SandMapHeightmapSurface"
	heightmap_surface_node.mesh = plane
	heightmap_surface_node.material_override = material
	heightmap_surface_node.visible = true
	sand_layer.add_child(heightmap_surface_node)
	if sand_mesh_instance != null:
		sand_mesh_instance.visible = false
	_build_surface_video_players()
	_apply_surface_controls()
	_apply_surface_texture_source()


func _build_surface_video_players() -> void:
	depth_video_player = _build_video_player(_source_path("depth_video", SAND_DEPTH_VIDEO_PATH))
	texture_video_player = _build_video_player(_source_path("texture_video", SAND_TEXTURE_VIDEO_PATH))
	_apply_surface_texture_source()


func _build_video_player(path: String) -> VideoStreamPlayer:
	if not ResourceLoader.exists(path):
		return null

	var stream := load(path)
	if stream == null:
		return null

	var player := VideoStreamPlayer.new()
	player.stream = stream
	player.autoplay = true
	player.loop = true
	player.volume_db = -80.0
	player.visible = false
	player.mouse_filter = Control.MOUSE_FILTER_IGNORE
	player.position = Vector2(-10000, -10000)
	player.size = Vector2.ZERO
	add_child(player)
	player.play()
	return player


func _apply_surface_texture_source() -> void:
	if heightmap_material == null:
		return
	if use_video_streams and depth_video_player != null:
		var depth_texture := depth_video_player.get_video_texture()
		if depth_texture != null:
			heightmap_material.set_shader_parameter("depth_map", depth_texture)
	elif static_depth_texture != null:
		heightmap_material.set_shader_parameter("depth_map", static_depth_texture)

	if use_video_streams and texture_video_player != null:
		var texture := texture_video_player.get_video_texture()
		if texture != null:
			heightmap_material.set_shader_parameter("texture_map", texture)
	elif static_surface_texture != null:
		heightmap_material.set_shader_parameter("texture_map", static_surface_texture)


func _source_path(key: String, fallback: String) -> String:
	return str(data_sources.get(key, fallback))


func _update_source_status(extra := "") -> void:
	if source_status_label == null:
		return
	var mode := "video streams" if use_video_streams else "static depth/material maps"
	var depth_path := _source_path("depth_video" if use_video_streams else "depth_map", SAND_DEPTH_VIDEO_PATH if use_video_streams else SAND_HEIGHTMAP_PATH)
	var texture_path := _source_path("texture_video" if use_video_streams else "texture_map", SAND_TEXTURE_VIDEO_PATH if use_video_streams else SAND_TEXTURE_PATH)
	source_status_label.text = "Surface source: %s | depth=%s | material=%s" % [mode, depth_path.get_file(), texture_path.get_file()]
	if not processed_surface_frames.is_empty() and surface_frame_index >= 0:
		var frame: Dictionary = processed_surface_frames[surface_frame_index]
		var depth_key := "detailDepth" if frame.has("detailDepth") else "cleanDepth"
		source_status_label.text += " | frame %d/%d %s @ %.2fs" % [
			surface_frame_index + 1,
			processed_surface_frames.size(),
			depth_key,
			float(frame.get("time", 0.0))
		]
	if extra != "":
		source_status_label.text += " | " + extra


func _update_hand_status() -> void:
	if hand_status_label == null:
		return
	var labels := PackedStringArray()
	for track in hand_tracks:
		if typeof(track) != TYPE_DICTIONARY:
			continue
		var samples: Array = track.get("samples", [])
		var count := int(track.get("joint_count", _track_joint_count(track)))
		var display_name := str(track.get("label", track.get("id", "hand")))
		labels.append("%s: %dpt / %d frames" % [display_name, count, samples.size()])
	hand_status_label.text = "Hand tracks: " + ("none" if labels.is_empty() else "\n".join(labels))


func _make_sand_mesh() -> ArrayMesh:
	var heights: Array = session.get("surface_heights", [])
	var width := int(session.get("surface_width", 24))
	var depth := int(session.get("surface_depth", 18))
	var scale := float(session.get("surface_scale", 0.25))
	var surface_tool := SurfaceTool.new()
	surface_tool.begin(Mesh.PRIMITIVE_TRIANGLES)

	for z in range(depth - 1):
		for x in range(width - 1):
			var a := _surface_vertex(x, z, width, depth, scale, heights)
			var b := _surface_vertex(x + 1, z, width, depth, scale, heights)
			var c := _surface_vertex(x, z + 1, width, depth, scale, heights)
			var d := _surface_vertex(x + 1, z + 1, width, depth, scale, heights)
			_add_triangle(surface_tool, a, c, b)
			_add_triangle(surface_tool, b, c, d)

	var mesh := surface_tool.commit()
	return mesh


func _surface_vertex(x: int, z: int, width: int, depth: int, scale: float, heights: Array) -> Vector3:
	var index := z * width + x
	var h := 0.0
	if index < heights.size():
		h = float(heights[index])
	return Vector3((x - width * 0.5) * scale, h, (z - depth * 0.5) * scale)


func _add_triangle(surface_tool: SurfaceTool, a: Vector3, b: Vector3, c: Vector3) -> void:
	var normal := Plane(a, b, c).normal
	surface_tool.set_normal(normal)
	surface_tool.add_vertex(a)
	surface_tool.set_normal(normal)
	surface_tool.add_vertex(b)
	surface_tool.set_normal(normal)
	surface_tool.add_vertex(c)


func _update_scene_from_time() -> void:
	_update_hand()
	_update_annotations()
	_update_highlights()
	_update_referential_links()
	_update_active_gesture()
	time_label.text = "%.2f / %.2f" % [playhead, duration]


func _update_hand() -> void:
	for track in hand_tracks:
		if typeof(track) != TYPE_DICTIONARY:
			continue
		var track_id := str(track.get("id", "hand"))
		if not hand_joint_nodes.has(track_id):
			continue
		var samples: Array = track.get("samples", [])
		var points := _sample_points(track, samples, playhead)
		var joints: Array = hand_joint_nodes[track_id]
		var centre := Vector3.ZERO
		var visible_joint_count := 0
		var show_landmarks := bool(track.get("show_landmarks", false))
		for i in range(joints.size()):
			var joint: MeshInstance3D = joints[i]
			if i < points.size():
				joint.visible = show_landmarks
				joint.position = points[i]
				centre += points[i]
				visible_joint_count += 1
			else:
				joint.visible = false
		_update_hand_bones(track_id, points, bool(track.get("show_skeleton", false)))
		_update_virtual_hand(track_id, points, bool(track.get("virtual_hand", true)))
		_update_hand_model(track_id, points, centre, visible_joint_count, track)


func _sample_points(track: Dictionary, samples: Array, time: float) -> Array[Vector3]:
	var points: Array[Vector3] = []
	if samples.is_empty():
		return points
	if samples.size() == 1:
		return _points_from_sample(samples[0])

	var bracket := _sample_bracket(samples, time)
	var left_index := int(bracket.get("left", 0))
	var right_index := int(bracket.get("right", left_index))
	if left_index == right_index:
		return _points_from_sample(samples[left_index])

	var left_sample: Dictionary = samples[left_index]
	var right_sample: Dictionary = samples[right_index]
	var left_time := float(left_sample.get("time", 0.0))
	var right_time := float(right_sample.get("time", left_time))
	var span: float = max(0.0001, right_time - left_time)
	var t: float = clamp((time - left_time) / span, 0.0, 1.0)
	var smooth_t: float = t * t * (3.0 - 2.0 * t)
	var mode := str(track.get("interpolation", "cubic")).to_lower()
	if mode == "nearest":
		return _points_from_sample(left_sample if t < 0.5 else right_sample)
	if mode == "linear":
		return _interpolate_sample_points(left_sample, right_sample, smooth_t)

	var prev_index: int = max(0, left_index - 1)
	var next_index: int = min(samples.size() - 1, right_index + 1)
	return _catmull_rom_sample_points(samples[prev_index], left_sample, right_sample, samples[next_index], smooth_t)


func _sample_bracket(samples: Array, time: float) -> Dictionary:
	var left_index := 0
	var right_index := 0
	var left_time := -INF
	var right_time := INF
	for index in range(samples.size()):
		var sample: Dictionary = samples[index]
		var sample_time := float(sample.get("time", 0.0))
		if sample_time <= time and sample_time >= left_time:
			left_time = sample_time
			left_index = index
		if sample_time >= time and sample_time <= right_time:
			right_time = sample_time
			right_index = index
	if left_time == -INF:
		left_index = right_index
	if right_time == INF:
		right_index = left_index
	return {"left": left_index, "right": right_index}


func _points_from_sample(sample: Dictionary) -> Array[Vector3]:
	var points: Array[Vector3] = []
	var raw_points: Array = sample.get("landmarks", sample.get("joints", []))
	for point in raw_points:
		points.append(_array_to_vec3(point))
	return points


func _interpolate_sample_points(left_sample: Dictionary, right_sample: Dictionary, t: float) -> Array[Vector3]:
	var left_points := _points_from_sample(left_sample)
	var right_points := _points_from_sample(right_sample)
	var count: int = min(left_points.size(), right_points.size())
	var points: Array[Vector3] = []
	for index in range(count):
		points.append(left_points[index].lerp(right_points[index], t))
	return points


func _catmull_rom_sample_points(prev_sample: Dictionary, left_sample: Dictionary, right_sample: Dictionary, next_sample: Dictionary, t: float) -> Array[Vector3]:
	var p0 := _points_from_sample(prev_sample)
	var p1 := _points_from_sample(left_sample)
	var p2 := _points_from_sample(right_sample)
	var p3 := _points_from_sample(next_sample)
	var count: int = min(min(p0.size(), p1.size()), min(p2.size(), p3.size()))
	var points: Array[Vector3] = []
	for index in range(count):
		points.append(_catmull_rom_vec3(p0[index], p1[index], p2[index], p3[index], t))
	return points


func _catmull_rom_vec3(p0: Vector3, p1: Vector3, p2: Vector3, p3: Vector3, t: float) -> Vector3:
	var t2: float = t * t
	var t3: float = t2 * t
	return (p1 * 2.0 + (p2 - p0) * t + (p0 * 2.0 - p1 * 5.0 + p2 * 4.0 - p3) * t2 + (-p0 + p1 * 3.0 - p2 * 3.0 + p3) * t3) * 0.5


func _update_hand_bones(track_id: String, points: Array[Vector3], show_bones: bool) -> void:
	if not hand_bone_nodes.has(track_id):
		return
	var bones: Array = hand_bone_nodes[track_id]
	for i in range(bones.size()):
		var bone: MeshInstance3D = bones[i]
		if not show_bones:
			bone.visible = false
			continue
		if i >= MEDIAPIPE_HAND_BONES.size():
			bone.visible = false
			continue
		var connection: Array = MEDIAPIPE_HAND_BONES[i]
		var a := int(connection[0])
		var b := int(connection[1])
		bone.visible = a < points.size() and b < points.size()
		if bone.visible:
			_place_bone_between(bone, points[a], points[b])


func _update_virtual_hand(track_id: String, points: Array[Vector3], enabled: bool) -> void:
	if not hand_virtual_nodes.has(track_id):
		return
	var virtual_hand: Dictionary = hand_virtual_nodes[track_id]
	var root: Node3D = virtual_hand.get("root", null)
	if root == null:
		return
	root.visible = enabled and points.size() >= 21
	if not root.visible:
		return
	hand_rendered_points[track_id] = points

	var palm: MeshInstance3D = virtual_hand.get("palm", null)
	if palm != null:
		palm.mesh = _make_hand_palm_mesh(points)

	var segments: Array = virtual_hand.get("segments", [])
	for i in range(segments.size()):
		var segment: MeshInstance3D = segments[i]
		if i >= VIRTUAL_HAND_SEGMENTS.size():
			segment.visible = false
			continue
		var connection: Array = VIRTUAL_HAND_SEGMENTS[i]
		var a := int(connection[0])
		var b := int(connection[1])
		segment.visible = a < points.size() and b < points.size()
		if segment.visible:
			_place_bone_between(segment, points[a], points[b])

	var tips: Array = virtual_hand.get("tips", [])
	for i in range(tips.size()):
		var tip: MeshInstance3D = tips[i]
		var tip_point := int(VIRTUAL_HAND_TIPS[i])
		tip.visible = tip_point < points.size()
		if tip.visible:
			tip.position = points[tip_point]


func _make_hand_palm_mesh(points: Array[Vector3]) -> ArrayMesh:
	var surface_tool := SurfaceTool.new()
	surface_tool.begin(Mesh.PRIMITIVE_TRIANGLES)
	for triangle in HAND_PALM_TRIANGLES:
		var a_index := int(triangle[0])
		var b_index := int(triangle[1])
		var c_index := int(triangle[2])
		if a_index >= points.size() or b_index >= points.size() or c_index >= points.size():
			continue
		var a := points[a_index]
		var b := points[b_index]
		var c := points[c_index]
		var normal := Plane(a, b, c).normal
		surface_tool.set_normal(normal)
		surface_tool.add_vertex(a)
		surface_tool.set_normal(normal)
		surface_tool.add_vertex(b)
		surface_tool.set_normal(normal)
		surface_tool.add_vertex(c)
	return surface_tool.commit()


func _place_bone_between(bone: MeshInstance3D, a: Vector3, b: Vector3) -> void:
	var delta := b - a
	var length := delta.length()
	if length < 0.001:
		bone.visible = false
		return

	var y_axis := delta / length
	var helper := Vector3.RIGHT if abs(y_axis.dot(Vector3.UP)) > 0.96 else Vector3.UP
	var x_axis := helper.cross(y_axis).normalized()
	var z_axis := x_axis.cross(y_axis).normalized()
	bone.transform = Transform3D(Basis(x_axis, y_axis * length, z_axis), (a + b) * 0.5)


func _update_hand_model(track_id: String, points: Array[Vector3], centre: Vector3, visible_joint_count: int, track: Dictionary) -> void:
	if not hand_model_nodes.has(track_id):
		return
	var model: MeshInstance3D = hand_model_nodes[track_id]
	if bool(track.get("virtual_hand", true)) and not bool(track.get("show_mesh_ghost", false)):
		model.visible = false
		return
	if visible_joint_count <= 0:
		model.visible = false
		return
	model.visible = true
	var palm_anchor := centre / float(visible_joint_count)
	if points.size() > 9:
		palm_anchor = (points[0] + points[5] + points[9] + points[13] + points[17]) / 5.0
	model.position = palm_anchor
	var model_scale := float(track.get("model_scale", 0.72))
	if points.size() > 9:
		var palm_span: float = max(0.08, points[5].distance_to(points[17]))
		model.scale = Vector3.ONE * model_scale * clamp(palm_span * 2.2, 0.45, 1.45)
	if bool(track.get("model_follow_orientation", true)) and points.size() > 9:
		var base_rotation := _array_to_vec3(track.get("model_rotation_degrees", [-90.0, 20.0, 0.0]))
		var forward := points[9] - points[0]
		forward.y = 0.0
		if forward.length() > 0.001:
			var yaw := rad_to_deg(atan2(forward.x, forward.z))
			model.rotation_degrees = Vector3(base_rotation.x, yaw + base_rotation.y, base_rotation.z)


func _update_annotations() -> void:
	var annotations: Array = session.get("annotations", [])
	for i in range(annotation_nodes.size()):
		if i >= annotations.size():
			continue
		var data: Dictionary = annotations[i]
		var start := float(data.get("start", 0.0))
		var end := float(data.get("end", duration))
		annotation_nodes[i].visible = playhead >= start and playhead <= end


func _update_active_gesture() -> void:
	if active_event_label == null:
		return
	var active := "none"
	for event in session.get("gesture_events", []):
		var start := float(event.get("start", 0.0))
		var end := float(event.get("end", duration))
		if playhead >= start and playhead <= end:
			active = "%s -> %s" % [str(event.get("label", event.get("kind", "gesture"))), str(event.get("target", ""))]
			break
	active_event_label.text = "Active gesture: " + active


func _build_surface_highlights() -> void:
	for region in session.get("surface_regions", []):
		var node := MeshInstance3D.new()
		node.name = "RegionHighlight_" + str(region.get("id", "region"))
		var plane := PlaneMesh.new()
		var size := _array_to_vec2(region.get("size", [0.8, 0.8]))
		plane.size = size
		node.mesh = plane
		node.position = _array_to_vec3(region.get("position", [0, 0.035, 0]))
		node.rotation_degrees = Vector3(0, float(region.get("rotation_degrees", 0.0)), 0)
		node.material_override = _highlight_material(_color_from_hex(str(region.get("color", "#f9a825"))))
		highlight_layer.add_child(node)
		highlight_nodes.append(node)


func _update_highlights() -> void:
	var regions: Array = session.get("surface_regions", [])
	for i in range(highlight_nodes.size()):
		if i >= regions.size():
			continue
		var data: Dictionary = regions[i]
		var start := float(data.get("start", 0.0))
		var end := float(data.get("end", duration))
		highlight_nodes[i].visible = playhead >= start and playhead <= end


func _build_referential_links() -> void:
	for reference in session.get("references", []):
		var line := MeshInstance3D.new()
		line.name = "Reference_" + str(reference.get("id", "link"))
		line.material_override = _line_material(_color_from_hex(str(reference.get("color", "#00bcd4"))))
		relation_layer.add_child(line)
		relation_nodes.append(line)


func _update_referential_links() -> void:
	var references: Array = session.get("references", [])
	for i in range(relation_nodes.size()):
		if i >= references.size():
			continue
		var data: Dictionary = references[i]
		var start := float(data.get("start", 0.0))
		var end := float(data.get("end", duration))
		var line := relation_nodes[i]
		line.visible = playhead >= start and playhead <= end
		if not line.visible:
			continue
		var source := _reference_point(str(data.get("source", "")))
		var target := _reference_point(str(data.get("target", "")))
		line.mesh = _make_line_mesh(source, target)


func _reference_point(id: String) -> Vector3:
	if id == "hand":
		return _first_visible_hand_point()
	if hand_rendered_points.has(id):
		return _hand_anchor_from_points(hand_rendered_points[id])
	if hand_virtual_nodes.has(id):
		var virtual_hand: Dictionary = hand_virtual_nodes[id]
		var palm: MeshInstance3D = virtual_hand.get("palm", null)
		if palm != null and palm.visible:
			return palm.global_position
	if hand_model_nodes.has(id):
		var model: MeshInstance3D = hand_model_nodes[id]
		if model.visible:
			return model.global_position
	if hand_joint_nodes.has(id):
		var joints: Array = hand_joint_nodes[id]
		for joint in joints:
			if joint is MeshInstance3D and joint.visible:
				return joint.global_position
	if object_nodes_by_id.has(id):
		return object_nodes_by_id[id].global_position + Vector3.UP * 0.35
	if annotation_nodes_by_id.has(id):
		return annotation_nodes_by_id[id].global_position
	for region in session.get("surface_regions", []):
		if str(region.get("id", "")) == id:
			return _array_to_vec3(region.get("position", [0, 0.08, 0])) + Vector3.UP * 0.18
	return Vector3.ZERO


func _first_visible_hand_point() -> Vector3:
	for track_id in hand_rendered_points.keys():
		return _hand_anchor_from_points(hand_rendered_points[track_id])
	for track_id in hand_virtual_nodes.keys():
		var virtual_hand: Dictionary = hand_virtual_nodes[track_id]
		var palm: MeshInstance3D = virtual_hand.get("palm", null)
		if palm != null and palm.visible:
			return palm.global_position
	for track_id in hand_model_nodes.keys():
		var model: MeshInstance3D = hand_model_nodes[track_id]
		if model.visible:
			return model.global_position
	for track_id in hand_joint_nodes.keys():
		var joints: Array = hand_joint_nodes[track_id]
		for joint in joints:
			if joint is MeshInstance3D and joint.visible:
				return joint.global_position
	return Vector3.ZERO


func _hand_anchor_from_points(points: Array) -> Vector3:
	if points.size() > 17:
		return (points[0] + points[5] + points[9] + points[13] + points[17]) / 5.0
	if points.is_empty():
		return Vector3.ZERO
	var centre := Vector3.ZERO
	for point in points:
		if point is Vector3:
			centre += point
	return centre / float(points.size())


func _make_line_mesh(a: Vector3, b: Vector3) -> ImmediateMesh:
	var mesh := ImmediateMesh.new()
	mesh.surface_begin(Mesh.PRIMITIVE_LINES)
	mesh.surface_add_vertex(a)
	mesh.surface_add_vertex(b)
	mesh.surface_end()
	return mesh


func _nearest_sample(samples: Array, time: float) -> Dictionary:
	var best: Dictionary = samples[0]
	var best_delta: float = abs(float(best.get("time", 0.0)) - time)
	for sample in samples:
		var sample_delta: float = abs(float(sample.get("time", 0.0)) - time)
		if sample_delta < best_delta:
			best = sample
			best_delta = sample_delta
	return best


func _set_layer_visible(key: String, visible: bool) -> void:
	match key:
		"sand":
			sand_layer.visible = visible
		"heightmap_surface":
			_set_heightmap_surface_enabled(visible)
		"gestures":
			gesture_layer.visible = visible
		"objects":
			object_layer.visible = visible
		"annotations":
			annotation_layer.visible = visible


func _on_condition_selected(index: int) -> void:
	var conditions := ["baseline", "no_audio", "no_gestures", "no_objects", "no_sand", "stage2"]
	current_condition = conditions[index]
	_apply_condition(current_condition)
	_log_event("condition_selected", {"condition": current_condition})


func _apply_condition(condition: String) -> void:
	var show_gestures := condition != "no_gestures"
	var show_objects := condition != "no_objects"
	var show_sand := condition != "no_sand"
	var show_annotations := condition == "stage2"
	_set_layer_toggle_value("gestures", show_gestures)
	_set_layer_toggle_value("objects", show_objects)
	_set_layer_toggle_value("sand", show_sand)
	_set_layer_toggle_value("annotations", show_annotations)
	_set_layer_visible("gestures", show_gestures)
	_set_layer_visible("objects", show_objects)
	_set_layer_visible("sand", show_sand)
	_set_layer_visible("annotations", show_annotations)
	_update_task_text()


func _set_layer_toggle_value(key: String, value: bool) -> void:
	if layer_toggles.has(key):
		layer_toggles[key].set_pressed_no_signal(value)


func _update_task_text() -> void:
	if task_label == null:
		return
	var tasks: Array = session.get("study_tasks", [])
	var lines := PackedStringArray()
	lines.append(str(session.get("title", "Sand story session")))
	lines.append("Condition: " + current_condition)
	for task in tasks:
		lines.append("- " + str(task.get("prompt", "")))
	task_label.text = "\n".join(lines)
	_update_participant_text()


func _update_participant_text() -> void:
	if participant_label == null:
		return
	var participants: Array = session.get("participants", [])
	participant_label.visible = not participants.is_empty()
	if participants.is_empty():
		participant_label.text = ""
		return

	var names := PackedStringArray()
	for participant in participants:
		if typeof(participant) == TYPE_DICTIONARY:
			var display_name := str(participant.get("display_name", participant.get("name", participant.get("id", ""))))
			if display_name != "":
				names.append(display_name)
		else:
			var name := str(participant)
			if name != "":
				names.append(name)
	participant_label.text = "Participants (%d):\n%s" % [names.size(), "、".join(names)]


func _on_mark_evidence_pressed() -> void:
	var visible_layers := {
		"sand": sand_layer.visible,
		"gestures": gesture_layer.visible,
		"objects": object_layer.visible,
		"annotations": annotation_layer.visible
	}
	evidence_label.text = "Evidence marked at %.2fs | layers=%s" % [playhead, JSON.stringify(visible_layers)]
	_log_event("evidence_marked", {
		"condition": current_condition,
		"camera_yaw": camera_yaw,
		"camera_pitch": camera_pitch,
		"camera_distance": camera_distance,
		"camera_target": [camera_target.x, camera_target.y, camera_target.z],
		"layers": visible_layers
	})


func _on_log_response_pressed() -> void:
	_log_event("response_draft", {
		"condition": current_condition,
		"notes": response_notes.text,
		"evidence": evidence_label.text
	})


func _toggle_focus_mode() -> void:
	focus_mode = not focus_mode
	if modality_panel != null:
		modality_panel.visible = not focus_mode
	if study_panel != null:
		study_panel.visible = not focus_mode
	if lower_dock_panel != null:
		lower_dock_panel.visible = not focus_mode
	if fixed_views_panel != null:
		fixed_views_panel.visible = (not focus_mode) and reference_views_visible
	if focus_button != null:
		focus_button.text = "Study panels" if focus_mode else "Focus 3D"
	_log_event("focus_mode", {"enabled": focus_mode})


func _toggle_reference_views() -> void:
	reference_views_visible = not reference_views_visible
	if fixed_views_panel != null:
		fixed_views_panel.visible = reference_views_visible and not focus_mode
	if reference_views_button != null:
		reference_views_button.text = "Hide refs" if reference_views_visible else "Reference views"
	_log_event("reference_views", {"visible": reference_views_visible})


func _set_heightmap_surface_enabled(enabled: bool) -> void:
	if sand_mesh_instance != null:
		sand_mesh_instance.visible = not enabled
	if heightmap_surface_node != null:
		heightmap_surface_node.visible = enabled
	if enabled:
		_apply_surface_texture_source()


func _on_play_pressed() -> void:
	is_playing = not is_playing
	play_button.text = "Pause" if is_playing else "Play"
	_set_surface_stream_playing(is_playing)
	_log_event("transport", {"playing": is_playing, "time": playhead})


func _on_time_changed(value: float) -> void:
	playhead = value
	_update_scene_from_time()


func _update_camera() -> void:
	var x := cos(camera_pitch) * sin(camera_yaw)
	var y := sin(-camera_pitch)
	var z := cos(camera_pitch) * cos(camera_yaw)
	camera.position = camera_target + Vector3(x, y, z) * camera_distance
	camera.look_at(camera_target, Vector3.UP)


func _log_event(event_name: String, payload: Dictionary) -> void:
	var entry := {
		"event": event_name,
		"time": Time.get_unix_time_from_system(),
		"playhead": playhead,
		"payload": payload
	}
	var file := FileAccess.open(LOG_PATH, FileAccess.READ_WRITE)
	if file == null:
		file = FileAccess.open(LOG_PATH, FileAccess.WRITE)
	if file == null:
		return
	file.seek_end()
	file.store_line(JSON.stringify(entry))


func _clear_children(node: Node) -> void:
	for child in node.get_children():
		child.queue_free()


func _material(color: Color, roughness: float) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = roughness
	return material


func _ghost_material(color: Color) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = Color(color.r, color.g, color.b, 0.38)
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	material.roughness = 0.74
	material.cull_mode = BaseMaterial3D.CULL_DISABLED
	return material


func _highlight_material(color: Color) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = Color(color.r, color.g, color.b, 0.38)
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.no_depth_test = true
	return material


func _line_material(color: Color) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	return material


func _panel_style(color: Color, radius: int) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.corner_radius_top_left = radius
	style.corner_radius_top_right = radius
	style.corner_radius_bottom_left = radius
	style.corner_radius_bottom_right = radius
	style.border_width_left = 1
	style.border_width_top = 1
	style.border_width_right = 1
	style.border_width_bottom = 1
	style.border_color = Color(1.0, 1.0, 1.0, 0.08)
	style.content_margin_left = 16
	style.content_margin_right = 16
	style.content_margin_top = 14
	style.content_margin_bottom = 14
	return style


func _apply_text_style(control: Control, font: Font, size: int) -> void:
	if font != null:
		control.add_theme_font_override("font", font)
	control.add_theme_font_size_override("font_size", size)


func _style_button(button: Button, variant := "secondary") -> void:
	var normal := Color(0.095, 0.115, 0.105, 0.98)
	var hover := Color(0.13, 0.16, 0.145, 1.0)
	var pressed := Color(0.18, 0.22, 0.2, 1.0)
	var text := Color(0.88, 0.9, 0.83)
	if variant == "primary":
		normal = Color(0.04, 0.38, 0.39, 1.0)
		hover = Color(0.05, 0.48, 0.49, 1.0)
		pressed = Color(0.03, 0.28, 0.3, 1.0)
		text = Color(0.96, 0.98, 0.91)
	elif variant == "toolbar":
		normal = Color(0.055, 0.064, 0.06, 0.98)
		hover = Color(0.09, 0.11, 0.1, 1.0)
		pressed = Color(0.13, 0.16, 0.14, 1.0)
	button.add_theme_stylebox_override("normal", _button_style(normal, 12, Color(1, 1, 1, 0.08)))
	button.add_theme_stylebox_override("hover", _button_style(hover, 12, Color(0.5, 0.86, 0.78, 0.42)))
	button.add_theme_stylebox_override("pressed", _button_style(pressed, 12, Color(0.95, 0.68, 0.38, 0.55)))
	button.add_theme_stylebox_override("focus", _button_style(Color(0.0, 0.0, 0.0, 0.0), 12, Color(0.85, 0.8, 0.48, 0.65)))
	button.add_theme_color_override("font_color", text)
	button.add_theme_color_override("font_hover_color", Color(1.0, 0.96, 0.78))
	button.add_theme_color_override("font_pressed_color", Color(1.0, 0.95, 0.78))
	_apply_text_style(button, ui_font_strong, 15)


func _button_style(color: Color, radius: int, border: Color) -> StyleBoxFlat:
	var style := _panel_style(color, radius)
	style.border_color = border
	style.content_margin_left = 12
	style.content_margin_right = 12
	style.content_margin_top = 8
	style.content_margin_bottom = 8
	return style


func _style_checkbox(toggle: CheckBox) -> void:
	toggle.add_theme_color_override("font_color", Color(0.86, 0.88, 0.82))
	toggle.add_theme_color_override("font_hover_color", Color(0.96, 0.93, 0.76))
	toggle.add_theme_color_override("font_pressed_color", Color(0.96, 0.93, 0.76))
	_apply_text_style(toggle, ui_font_strong, 16)


func _sand_material() -> Material:
	if ResourceLoader.exists(SAND_SHADER_PATH):
		var shader := load(SAND_SHADER_PATH)
		if shader is Shader:
			var material := ShaderMaterial.new()
			material.shader = shader
			material.set_shader_parameter("height_scale", 0.06)
			material.set_shader_parameter("noise_scale", 3.0)
			material.set_shader_parameter("offset", Vector2.ZERO)
			material.set_shader_parameter("color_strength", 0.55)
			return material
	return _material(Color(0.86, 0.73, 0.43), 0.85)


func _reload_static_surface_textures() -> void:
	var depth_path := _source_path("depth_map", SAND_HEIGHTMAP_PATH)
	var texture_path := _source_path("texture_map", SAND_TEXTURE_PATH)
	static_depth_texture = null
	static_surface_texture = null
	static_surface_mask_texture = null

	if ResourceLoader.exists(depth_path):
		var depth_map := load(depth_path)
		if depth_map is Texture2D:
			static_depth_texture = depth_map
	if ResourceLoader.exists(texture_path):
		var texture_map := load(texture_path)
		if texture_map is Texture2D:
			static_surface_texture = texture_map

	var mask_path := str(data_sources.get("surface_mask", ""))
	if mask_path != "" and ResourceLoader.exists(mask_path):
		var mask_map := load(mask_path)
		if mask_map is Texture2D:
			static_surface_mask_texture = mask_map

	if heightmap_material != null:
		if static_depth_texture != null:
			heightmap_material.set_shader_parameter("depth_map", static_depth_texture)
			_apply_depth_material_profile()
		if static_surface_texture != null:
			heightmap_material.set_shader_parameter("texture_map", static_surface_texture)
		if static_surface_mask_texture != null:
			heightmap_material.set_shader_parameter("surface_mask", static_surface_mask_texture)
			heightmap_material.set_shader_parameter("use_surface_mask", true)
		else:
			heightmap_material.set_shader_parameter("use_surface_mask", false)


func _heightmap_material() -> Material:
	if not ResourceLoader.exists(SAND_DEPTH_SHADER_PATH):
		return null
	var depth_path := _source_path("depth_map", SAND_HEIGHTMAP_PATH)
	var texture_path := _source_path("texture_map", SAND_TEXTURE_PATH)
	if not ResourceLoader.exists(depth_path):
		return null
	if not ResourceLoader.exists(texture_path):
		return null

	var shader := load(SAND_DEPTH_SHADER_PATH)
	if not shader is Shader:
		return null

	var material := ShaderMaterial.new()
	material.shader = shader
	heightmap_material = material
	_reload_static_surface_textures()
	if static_depth_texture == null or static_surface_texture == null:
		heightmap_material = null
		return null
	material.set_shader_parameter("arg_1", 11.625)
	material.set_shader_parameter("arg_2", 0.57)
	_apply_depth_material_profile()
	if static_surface_mask_texture != null:
		material.set_shader_parameter("surface_mask", static_surface_mask_texture)
		material.set_shader_parameter("use_surface_mask", true)
	else:
		material.set_shader_parameter("use_surface_mask", false)
	material.set_shader_parameter("depth_uv_offset", Vector2.ZERO)
	material.set_shader_parameter("texture_uv_offset", Vector2.ZERO)
	material.set_shader_parameter("depth_uv_scale", Vector2.ONE)
	material.set_shader_parameter("texture_uv_scale", Vector2.ONE)
	material.set_shader_parameter("displacement_scale", 1.0)
	material.set_shader_parameter("material_strength", 0.0)
	return material


func _apply_depth_material_profile() -> void:
	if heightmap_material == null:
		return
	var depth_path := _source_path("depth_map", SAND_HEIGHTMAP_PATH)
	var is_fused_depth := depth_path.get_file().begins_with("detail_depth_fused_")
	var is_detail_depth := depth_path.get_file().begins_with("detail_depth_")
	if is_fused_depth:
		heightmap_material.set_shader_parameter("arg_1", 3.4)
		heightmap_material.set_shader_parameter("background", 0.5)
		heightmap_material.set_shader_parameter("eps_0", 0.012)
		heightmap_material.set_shader_parameter("eps_1", 0.11)
	elif is_detail_depth:
		heightmap_material.set_shader_parameter("arg_1", 3.0)
		heightmap_material.set_shader_parameter("background", 0.5)
		heightmap_material.set_shader_parameter("eps_0", 0.004)
		heightmap_material.set_shader_parameter("eps_1", 0.08)
	else:
		heightmap_material.set_shader_parameter("arg_1", 11.625)
		heightmap_material.set_shader_parameter("background", 1.0)
		heightmap_material.set_shader_parameter("eps_0", 0.08)
		heightmap_material.set_shader_parameter("eps_1", 0.415)


func _apply_surface_controls() -> void:
	if heightmap_material == null:
		return
	heightmap_material.set_shader_parameter(
		"depth_uv_offset",
		Vector2(float(surface_controls["depth_u"]), float(surface_controls["depth_v"]))
	)
	heightmap_material.set_shader_parameter(
		"texture_uv_offset",
		Vector2(float(surface_controls["texture_u"]), float(surface_controls["texture_v"]))
	)
	heightmap_material.set_shader_parameter("displacement_scale", float(surface_controls["displacement"]))
	heightmap_material.set_shader_parameter("material_strength", float(surface_controls["material_strength"]))
	var calibration: Dictionary = data_sources.get("calibration", {})
	heightmap_material.set_shader_parameter(
		"depth_uv_scale",
		_array_to_vec2(calibration.get("depth_uv_scale", [1.0, 1.0]))
	)
	heightmap_material.set_shader_parameter(
		"texture_uv_scale",
		_array_to_vec2(calibration.get("texture_uv_scale", [1.0, 1.0]))
	)


func _set_surface_stream_playing(playing: bool) -> void:
	for player in [depth_video_player, texture_video_player]:
		if player == null:
			continue
		if playing:
			player.paused = false
		else:
			player.paused = true


func _array_to_vec3(value) -> Vector3:
	if typeof(value) != TYPE_ARRAY or value.size() < 3:
		return Vector3.ZERO
	return Vector3(float(value[0]), float(value[1]), float(value[2]))


func _array_to_vec2(value) -> Vector2:
	if typeof(value) != TYPE_ARRAY or value.size() < 2:
		return Vector2.ONE
	return Vector2(float(value[0]), float(value[1]))


func _color_from_hex(hex: String) -> Color:
	var normalized := hex.strip_edges()
	if normalized.begins_with("#"):
		normalized = normalized.substr(1)
	return Color.html(normalized)
