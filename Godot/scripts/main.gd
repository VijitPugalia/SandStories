extends Node3D

const DEFAULT_SESSION_PATH := "res://data/sample_session/session.json"
const LOG_PATH := "user://interaction_log.jsonl"
const HAND_MODEL_LEFT_PATH := "res://assets/models/hand_left.obj"
const HAND_MODEL_RIGHT_PATH := "res://assets/models/hand_right.obj"
const HAND_RIG_LEFT_PATH := "res://assets/models/godot_humanoid_hands/LeftHandHumanoid.gltf"
const HAND_RIG_RIGHT_PATH := "res://assets/models/godot_humanoid_hands/RightHandHumanoid.gltf"
const SAND_SHADER_PATH := "res://assets/shaders/sand_surface.gdshader"
const SAND_DEPTH_SHADER_PATH := "res://assets/shaders/sand_depth.gdshader"
const HAND_HOLOGRAM_SHADER_PATH := "res://assets/shaders/hologram_hand.gdshader"
const TOPDOWN_HAND_OVERLAY_SHADER_PATH := "res://assets/shaders/topdown_hand_overlay.gdshader"
const TOPDOWN_HAND_RGBD_SHADER_PATH := "res://assets/shaders/topdown_hand_rgbd.gdshader"
const TOPDOWN_HAND_RGBD_SHELL_SHADER_PATH := "res://assets/shaders/topdown_hand_rgbd_shell.gdshader"
const MANO_HAND_BEAUTY_SHADER_PATH := "res://assets/shaders/mano_hand_beauty.gdshader"
const EXPERIMENT_RUNNER_SCRIPT_PATH := "res://scripts/experiment_runner.gd"
const EXPERIMENT_PROTOCOL_PATH := "res://data/experiment_protocol.json"
const EXPERIMENT_SUBMISSION_DIR := "user://experiment_submissions"
const CJK_FONT_PATH := "res://assets/fonts/NotoSansSC-VF.ttf"
const FONT_WEIGHT_AXIS := 0x77676874 # "wght"
const SAND_HEIGHTMAP_PATH := "res://assets/heightmaps/sand2_heightmap_square_lowfreq.png"
const SAND_TEXTURE_PATH := "res://assets/source_images/sand2_original_square.png"
const SAND_DEPTH_VIDEO_PATH := "res://assets/video/depth_stream.ogv"
const SAND_TEXTURE_VIDEO_PATH := "res://assets/video/texture_stream.ogv"
const SURFACE_PREFETCH_AHEAD := 12
const SURFACE_CACHE_BEHIND := 3
const SURFACE_AUTOPLAY_BUFFER_FRAMES := 8
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
const VIRTUAL_HAND_KNUCKLES := [0, 5, 9, 13, 17]
const VIRTUAL_HAND_PALM_OUTLINE := [0, 5, 9, 13, 17]
const HAND_PALM_TRIANGLES := [
	[0, 5, 9],
	[0, 9, 13],
	[0, 13, 17]
]
const SESSION_PRESETS := [
	{"label": "Sample study session", "path": DEFAULT_SESSION_PATH},
	{"label": "Kinect raw RGB-D", "path": "res://assets/processed_sessions/session_kinect_20260623_154953/session.json"},
	{"label": "Temporal smooth", "path": "res://assets/processed_sessions/session_kinect_20260623_154953_temporal_smooth_godot/session.json"},
	{"label": "Balanced detail", "path": "res://assets/processed_sessions/session_kinect_20260623_154953_last12_balanced_detail_godot/session.json"},
	{"label": "SAM RGB repair bold", "path": "res://assets/processed_sessions/session_kinect_20260623_154953_object_removed_sam_full_gpu_rgb_reference_repair_bold/session.json"},
	{"label": "RGB-delta depth v44", "path": "res://assets/processed_sessions/session_kinect_20260623_154953_object_removed_rgb_delta_depth_v44/session.json"},
	{"label": "Posterior contact intent82", "path": "res://assets/processed_sessions/session_kinect_20260623_154953_object_removed_posterior_repair_core_target_contact_intent82/session.json"},
	{"label": "Azure Kinect 2026-08-14 (your recording)", "path": "res://assets/processed_sessions/session_azure_kinect_20260814_131426/session.json"},
	{"label": "Azure Kinect 2026-08-14 top-down (new)", "path": "res://assets/processed_sessions/session_azure_kinect_20260814_142712/session.json"},
	{"label": "Azure Kinect 2026-08-14 hand-removed (ProPainter)", "path": "res://assets/processed_sessions/session_azure_kinect_20260814_142712_hand_removed_propainter/session.json"}
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
var audio_user_enabled := true
var unicode_smoke_test_enabled := false
var ui_font: Font
var ui_font_strong: Font
var ui_font_display: Font
var web_command_callback
var web_bridge_ready := false
var web_embed_mode := false
var web_state_emit_elapsed := 0.0
var training_guide_mode := "off"
var training_guide_elapsed := 0.0

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
var topdown_hand_surface_node: MeshInstance3D
var topdown_hand_material: ShaderMaterial
var mano_hand_surface_node: MeshInstance3D
var mano_hand_material: Material
var static_depth_texture: Texture2D
var static_surface_texture: Texture2D
var static_surface_mask_texture: Texture2D
var static_topdown_hand_texture: Texture2D
var static_topdown_hand_geometry_texture: Texture2D
var depth_video_player: VideoStreamPlayer
var texture_video_player: VideoStreamPlayer
var audio_player: AudioStreamPlayer
var processed_surface_frames: Array = []
var processed_surface_base_dir := ""
var external_session_base_dir := ""
var current_session_path := ""
var session_load_generation := 0
var surface_frame_index := -1
var surface_frame_pending_index := -1
var surface_baseline_height_offset := 0.0
var surface_texture_cache := {}
var surface_texture_pending := {}
var mano_mesh_cache := {}
var mano_mesh_pending := {}
var hand_tracks: Array = []
var hand_track_roots := {}
var hand_model_nodes := {}
var hand_joint_nodes := {}
var hand_bone_nodes := {}
var hand_virtual_nodes := {}
var hand_rig_nodes := {}
var hand_tool_nodes := {}
var hand_rendered_points := {}
var object_nodes: Array[MeshInstance3D] = []
var annotation_nodes: Array[Node3D] = []
var highlight_nodes: Array[Node3D] = []
var relation_nodes: Array[MeshInstance3D] = []
var object_nodes_by_id := {}
var annotation_nodes_by_id := {}
var current_condition := "baseline"
var training_guide_root: Control
var training_guide_card: PanelContainer
var training_guide_kicker: Label
var training_guide_title: Label
var training_guide_body: Label
var training_guide_beacon: MeshInstance3D
var training_guide_target_fill: MeshInstance3D
var training_guide_world_label: Label3D

var play_button: Button
var time_slider: HSlider
var time_label: Label
var session_option: OptionButton
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
var hud_root: Control
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
var experiment_runner
var experiment_mode := false
var experiment_stage := ""
var experiment_protocol := {}
var experiment_event_buffer: Array = []
var researcher_controls: Array[Control] = []
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
	_build_training_guide()
	_setup_web_bridge()
	web_embed_mode = _web_query_flag("embed")
	if hud_root != null:
		hud_root.visible = not web_embed_mode
	var initial_session_path := DEFAULT_SESSION_PATH
	if not OS.has_feature("web"):
		var requested_session := _launch_value("session")
		if requested_session != "":
			initial_session_path = requested_session
	await _load_session(initial_session_path)
	await _apply_launch_params()
	var requested_time := _launch_value("time")
	if requested_time != "":
		_seek_playhead(float(requested_time))
	var launch_study := _launch_value("study").to_lower()
	if launch_study in ["stage1", "pilot"]:
		# Stage 1 must train on the complete representation before revealing
		# the assigned ablation condition. The Web query parser may already
		# have read ?condition=..., so explicitly restore the baseline here.
		current_condition = "baseline"
	elif launch_study == "stage2":
		current_condition = "stage2"
	_apply_condition(current_condition)
	_configure_experiment_mode()
	_update_scene_from_time()
	_update_camera()
	web_bridge_ready = true
	_emit_web_message("ready", _web_state_snapshot())
	_emit_web_state()
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
	_update_training_guide(delta)
	if is_playing:
		playhead += delta
		if playhead >= duration:
			playhead = duration
			is_playing = false
			if play_button != null:
				play_button.text = "Play"
			_set_surface_stream_playing(false)
			_sync_audio_playback()
			if web_bridge_ready:
				_emit_web_state()
		time_slider.set_value_no_signal(playhead)
		_update_scene_from_time()
	if web_bridge_ready and is_playing:
		web_state_emit_elapsed += delta
		if web_state_emit_elapsed >= 0.20:
			web_state_emit_elapsed = 0.0
			_emit_web_state()


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
	light.name = "RakingKey"
	light.rotation_degrees = Vector3(-28, -42, 0)
	light.light_color = Color(1.0, 0.91, 0.78)
	light.light_energy = 1.65
	light.shadow_enabled = true
	add_child(light)

	var fill_light := DirectionalLight3D.new()
	fill_light.name = "CoolFill"
	fill_light.rotation_degrees = Vector3(-62, 132, 0)
	fill_light.light_color = Color(0.68, 0.80, 1.0)
	fill_light.light_energy = 0.34
	add_child(fill_light)

	var environment := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.58, 0.63, 0.60)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.55, 0.60, 0.64)
	env.ambient_light_energy = 0.30
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


func _build_training_guide() -> void:
	var canvas := CanvasLayer.new()
	canvas.name = "TrainingGuideHUD"
	canvas.layer = 20
	add_child(canvas)

	training_guide_root = Control.new()
	training_guide_root.name = "TrainingGuideRoot"
	training_guide_root.set_anchors_preset(Control.PRESET_FULL_RECT)
	training_guide_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	training_guide_root.visible = false
	if ui_font != null:
		var guide_theme := Theme.new()
		guide_theme.set_default_font(ui_font)
		guide_theme.set_default_font_size(15)
		training_guide_root.theme = guide_theme
	canvas.add_child(training_guide_root)

	training_guide_card = PanelContainer.new()
	training_guide_card.name = "TrainingGuideCard"
	training_guide_card.anchor_left = 0.0
	training_guide_card.anchor_top = 0.0
	training_guide_card.anchor_right = 0.0
	training_guide_card.anchor_bottom = 0.0
	training_guide_card.offset_left = 18
	training_guide_card.offset_top = 18
	training_guide_card.offset_right = 408
	training_guide_card.offset_bottom = 150
	training_guide_card.mouse_filter = Control.MOUSE_FILTER_IGNORE
	training_guide_card.add_theme_stylebox_override(
		"panel",
		_panel_style(Color(0.035, 0.055, 0.06, 0.94), 16)
	)
	training_guide_root.add_child(training_guide_card)

	var guide_stack := VBoxContainer.new()
	guide_stack.add_theme_constant_override("separation", 5)
	guide_stack.mouse_filter = Control.MOUSE_FILTER_IGNORE
	training_guide_card.add_child(guide_stack)

	training_guide_kicker = Label.new()
	training_guide_kicker.text = "GUIDED PRACTICE"
	training_guide_kicker.add_theme_color_override(
		"font_color",
		Color(0.97, 0.72, 0.36)
	)
	_apply_text_style(training_guide_kicker, ui_font_strong, 12)
	guide_stack.add_child(training_guide_kicker)

	training_guide_title = Label.new()
	training_guide_title.text = "Watch the action unfold"
	training_guide_title.add_theme_color_override(
		"font_color",
		Color(0.97, 0.98, 0.94)
	)
	_apply_text_style(training_guide_title, ui_font_display, 22)
	guide_stack.add_child(training_guide_title)

	training_guide_body = Label.new()
	training_guide_body.text = "Follow the highlighted control and the target on the sand."
	training_guide_body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	training_guide_body.add_theme_color_override(
		"font_color",
		Color(0.80, 0.86, 0.84)
	)
	_apply_text_style(training_guide_body, ui_font, 14)
	guide_stack.add_child(training_guide_body)

	var ring_mesh := TorusMesh.new()
	ring_mesh.inner_radius = 0.28
	ring_mesh.outer_radius = 0.36
	ring_mesh.rings = 32
	ring_mesh.ring_segments = 12
	training_guide_beacon = MeshInstance3D.new()
	training_guide_beacon.name = "TrainingTargetRing"
	training_guide_beacon.mesh = ring_mesh
	training_guide_beacon.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	training_guide_beacon.material_override = _training_guide_material(
		Color(1.0, 0.58, 0.12, 0.96)
	)
	training_guide_beacon.visible = false
	add_child(training_guide_beacon)

	var fill_mesh := CylinderMesh.new()
	fill_mesh.top_radius = 0.23
	fill_mesh.bottom_radius = 0.23
	fill_mesh.height = 0.012
	fill_mesh.radial_segments = 32
	training_guide_target_fill = MeshInstance3D.new()
	training_guide_target_fill.name = "TrainingTargetFill"
	training_guide_target_fill.mesh = fill_mesh
	training_guide_target_fill.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	training_guide_target_fill.material_override = _training_guide_material(
		Color(1.0, 0.62, 0.18, 0.18)
	)
	training_guide_target_fill.visible = false
	add_child(training_guide_target_fill)

	training_guide_world_label = Label3D.new()
	training_guide_world_label.name = "TrainingTargetLabel"
	training_guide_world_label.text = "WATCH HERE"
	training_guide_world_label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	training_guide_world_label.no_depth_test = true
	training_guide_world_label.font = ui_font_strong
	training_guide_world_label.font_size = 30
	training_guide_world_label.outline_size = 10
	training_guide_world_label.modulate = Color(1.0, 0.88, 0.57)
	training_guide_world_label.outline_modulate = Color(0.03, 0.05, 0.05, 0.92)
	training_guide_world_label.visible = false
	add_child(training_guide_world_label)


func _training_guide_material(color: Color) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.emission_enabled = true
	material.emission = Color(color.r, color.g, color.b)
	material.emission_energy_multiplier = 1.6
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.no_depth_test = true
	return material


func _set_training_guide(mode: String, step: int, total: int) -> void:
	var guides := {
		"playback": {
			"title": "Watch the action unfold",
			"body": "Play the session and notice how the virtual hand and sand surface change together.",
			"label": "WATCH THE TRACE",
			"target": Vector3(0.35, 0.16, 0.10),
		},
		"camera": {
			"title": "Change your point of view",
			"body": "Compare the same trace from above and from an oblique 3D view.",
			"label": "INSPECT FROM TWO VIEWS",
			"target": Vector3(0.0, 0.16, 0.0),
		},
		"layers": {
			"title": "Separate the information",
			"body": "Hide and restore the virtual hand, then judge what the sand surface alone reveals.",
			"label": "COMPARE THE LAYERS",
			"target": Vector3(-0.40, 0.16, 0.18),
		},
		"occlusion": {
			"title": "Look behind the ridge",
			"body": "Use an oblique view to inspect an area that is compressed in the top view.",
			"label": "LOOK BEHIND THE RIDGE",
			"target": Vector3(-0.68, 0.16, 0.58),
		},
		"segmentation": {
			"title": "Read the physical relief",
			"body": "Remove RGB colour temporarily and read the height changes directly from the surface.",
			"label": "READ THE RELIEF",
			"target": Vector3(0.55, 0.16, -0.12),
		},
		"referential": {
			"title": "Link action to trace",
			"body": "Follow the hand movement, timeline, and relation cue as one combined piece of evidence.",
			"label": "LINK ACTION TO TRACE",
			"target": Vector3(0.05, 0.16, 0.02),
		},
	}
	training_guide_mode = mode if guides.has(mode) else "off"
	training_guide_elapsed = 0.0
	var visible := training_guide_mode != "off"
	training_guide_root.visible = visible
	training_guide_beacon.visible = visible
	training_guide_target_fill.visible = visible
	training_guide_world_label.visible = visible
	if not visible:
		return

	var guide: Dictionary = guides[training_guide_mode]
	var safe_total := maxi(total, 1)
	var safe_step := clampi(step, 1, safe_total)
	training_guide_kicker.text = "GUIDED PRACTICE · %d / %d" % [
		safe_step,
		safe_total,
	]
	training_guide_title.text = str(guide["title"])
	training_guide_body.text = str(guide["body"])
	training_guide_world_label.text = str(guide["label"])
	var target: Vector3 = guide["target"]
	training_guide_beacon.position = target
	training_guide_target_fill.position = target - Vector3(0.0, 0.01, 0.0)
	training_guide_world_label.position = target + Vector3(0.0, 0.42, 0.0)
	_log_event("training_guide", {
		"mode": training_guide_mode,
		"step": safe_step,
		"total": safe_total,
	})


func _update_training_guide(delta: float) -> void:
	if training_guide_mode == "off" or training_guide_beacon == null:
		return
	training_guide_elapsed += delta
	var pulse := 1.0 + 0.10 * sin(training_guide_elapsed * TAU * 0.72)
	training_guide_beacon.scale = Vector3.ONE * pulse
	training_guide_beacon.rotation.y = training_guide_elapsed * 0.42
	training_guide_target_fill.scale = Vector3.ONE * (0.96 + 0.10 * pulse)
	training_guide_world_label.modulate.a = (
		0.84 + 0.16 * sin(training_guide_elapsed * TAU * 0.72)
	)


func _build_ui() -> void:
	var canvas := CanvasLayer.new()
	canvas.name = "HUD"
	add_child(canvas)

	hud_root = Control.new()
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
	researcher_controls.append(condition_option)

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
	researcher_controls.append(source_status_label)

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

	var session_title := Label.new()
	session_title.text = "RGB-D Version"
	_apply_text_style(session_title, ui_font_strong, 17)
	session_title.add_theme_color_override("font_color", Color(0.58, 0.72, 0.69))
	root.add_child(session_title)
	researcher_controls.append(session_title)

	session_option = OptionButton.new()
	for preset in SESSION_PRESETS:
		session_option.add_item(str(preset.get("label", "Session")))
	session_option.item_selected.connect(_on_session_selected)
	_style_button(session_option, "toolbar")
	root.add_child(session_option)
	researcher_controls.append(session_option)

	_add_layer_toggle(root, "sand", "RGB-D sand surface", true)
	_add_layer_toggle(root, "heightmap_surface", "Use reconstructed depth map", true)
	_add_layer_toggle(root, "gestures", "Virtual hand / gestures", true)
	_add_layer_toggle(root, "objects", "Objects / tools", true)
	_add_layer_toggle(root, "audio", "Narration audio", true)
	_add_layer_toggle(root, "annotations", "Annotations + links", false)

	var source_title := Label.new()
	source_title.text = "Input Streams"
	_apply_text_style(source_title, ui_font_strong, 17)
	source_title.add_theme_color_override("font_color", Color(0.58, 0.72, 0.69))
	root.add_child(source_title)
	researcher_controls.append(source_title)

	video_stream_toggle = CheckBox.new()
	video_stream_toggle.text = "Synced OGV depth/material"
	video_stream_toggle.button_pressed = use_video_streams
	video_stream_toggle.toggled.connect(func(value: bool) -> void:
		use_video_streams = value
		_apply_surface_texture_source()
		_set_surface_stream_playing(is_playing and use_video_streams)
		_update_source_status()
		_log_event("surface_source_toggle", {"use_video_streams": use_video_streams})
	)
	_style_checkbox(video_stream_toggle)
	root.add_child(video_stream_toggle)
	researcher_controls.append(video_stream_toggle)

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
	researcher_controls.append(hand_status_label)

	var calibration := VBoxContainer.new()
	calibration.name = "Calibration"
	calibration.add_theme_constant_override("separation", 5)
	root.add_child(calibration)
	researcher_controls.append(calibration)

	var surface_label := Label.new()
	surface_label.text = "Depth / Material Fit"
	_apply_text_style(surface_label, ui_font_strong, 17)
	surface_label.add_theme_color_override("font_color", Color(0.58, 0.72, 0.69))
	calibration.add_child(surface_label)

	_add_surface_slider(calibration, "depth_u", "Depth U", -1.0, 1.0, 0.001, 0.0)
	_add_surface_slider(calibration, "depth_v", "Depth V", -1.0, 1.0, 0.001, 0.0)
	_add_surface_slider(calibration, "texture_u", "Texture U", -1.0, 1.0, 0.001, 0.0)
	_add_surface_slider(calibration, "texture_v", "Texture V", -1.0, 1.0, 0.001, 0.0)
	_add_surface_slider(calibration, "displacement", "Height", -8.0, 8.0, 0.01, 1.0)
	_add_surface_slider(calibration, "material_strength", "Map blend", 0.0, 1.0, 0.01, 0.0)
	_add_surface_frame_controls(calibration)

	var hint := Label.new()
	hint.text = "Camera: WASD glide, Shift boost, drag orbit, wheel/Q/E zoom, 1 top, 2 front, 3 orbit."
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_apply_text_style(hint, ui_font, 13)
	hint.add_theme_color_override("font_color", Color(0.76, 0.8, 0.75))
	root.add_child(hint)

	_build_study_panel(hud_root)
	_build_experiment_panel(hud_root)
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
	researcher_controls.append(lower_dock_panel)

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


func _build_experiment_panel(canvas: Control) -> void:
	if not ResourceLoader.exists(EXPERIMENT_RUNNER_SCRIPT_PATH):
		return
	var runner_script := load(EXPERIMENT_RUNNER_SCRIPT_PATH)
	if not runner_script is Script:
		return
	experiment_runner = runner_script.new()
	experiment_runner.visible = false
	experiment_runner.anchor_left = 1.0
	experiment_runner.anchor_top = 0.0
	experiment_runner.anchor_right = 1.0
	experiment_runner.anchor_bottom = 1.0
	experiment_runner.offset_left = -500
	experiment_runner.offset_top = 86
	experiment_runner.offset_right = -16
	experiment_runner.offset_bottom = -118
	experiment_runner.condition_requested.connect(
		_on_experiment_condition_requested
	)
	experiment_runner.evidence_requested.connect(
		_on_experiment_evidence_requested
	)
	experiment_runner.submission_ready.connect(
		_on_experiment_submission_ready
	)
	experiment_runner.event_emitted.connect(
		func(event_name: String, payload: Dictionary) -> void:
			_log_event(event_name, payload)
	)
	canvas.add_child(experiment_runner)


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
	viewport.render_target_update_mode = SubViewport.UPDATE_DISABLED
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
	view_camera.current = true
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
	session_load_generation += 1
	var generation := session_load_generation
	if _is_http_path(path):
		await _load_remote_session(path, generation)
		return

	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("Cannot open session file: " + path)
		return

	var parsed = JSON.parse_string(file.get_as_text())
	await _apply_session_payload(parsed, path, "", generation)


func _load_remote_session(path: String, generation: int) -> void:
	var text := await _http_get_text(path)
	if generation != session_load_generation or text == "":
		return
	var parsed = JSON.parse_string(text)
	await _apply_session_payload(
		parsed,
		path,
		path.get_base_dir(),
		generation
	)


func _apply_session_payload(
	parsed,
	path: String,
	remote_base_dir: String,
	generation: int
) -> void:
	if generation != session_load_generation:
		return
	if typeof(parsed) != TYPE_DICTIONARY:
		push_error("Invalid session JSON: " + path)
		return

	playhead = 0.0
	is_playing = false
	if time_slider != null:
		time_slider.set_value_no_signal(0.0)
	if play_button != null:
		play_button.text = "Play"

	session = parsed
	data_sources = session.get("data_sources", {})
	external_session_base_dir = remote_base_dir
	if external_session_base_dir != "":
		_rebase_external_data_sources()
	surface_texture_cache.clear()
	surface_texture_pending.clear()
	mano_mesh_cache.clear()
	mano_mesh_pending.clear()
	surface_frame_pending_index = -1
	await _load_processed_surface_frames(generation)
	if generation != session_load_generation:
		return
	await _load_external_hand_tracks(generation)
	if generation != session_load_generation:
		return
	await _load_session_audio(generation)
	if generation != session_load_generation:
		return
	use_video_streams = bool(data_sources.get("use_video_streams", false))
	_apply_session_calibration_defaults()
	if video_stream_toggle != null:
		video_stream_toggle.set_pressed_no_signal(use_video_streams)
	duration = float(session.get("duration", 1.0))
	if duration <= 0.0 and not processed_surface_frames.is_empty():
		var last_frame: Dictionary = processed_surface_frames[processed_surface_frames.size() - 1]
		duration = max(0.0, float(last_frame.get("time", 0.0)))
	time_slider.max_value = duration
	_build_session_nodes()
	_prefetch_surface_window(surface_frame_index)
	await _wait_for_initial_surface_textures(15000, generation)
	if generation != session_load_generation:
		return
	_update_source_status()
	_log_event("session_loaded", {"path": path, "duration": duration})
	if _should_autoplay_session(path):
		await _wait_for_surface_buffer(
			SURFACE_AUTOPLAY_BUFFER_FRAMES,
			15000,
			generation
		)
		if generation != session_load_generation:
			return
		is_playing = true
		if play_button != null:
			play_button.text = "Pause"
		_set_surface_stream_playing(use_video_streams)
		_sync_audio_playback(true)
	current_session_path = path
	_update_session_selector(path)


func _on_session_selected(index: int) -> void:
	if index < 0 or index >= SESSION_PRESETS.size():
		return
	var path := _runtime_session_path(str(SESSION_PRESETS[index].get("path", "")))
	if path == "":
		return
	playhead = 0.0
	if time_slider != null:
		time_slider.set_value_no_signal(0.0)
	_load_session(path)


func _runtime_session_path(path: String) -> String:
	if path == "" or _is_http_path(path) or path.begins_with("user://"):
		return path
	if OS.has_feature("web") and external_session_base_dir != "" and path.begins_with("res://assets/processed_sessions/"):
		return external_session_base_dir.get_base_dir().path_join(path.trim_prefix("res://assets/processed_sessions/"))
	return path


func _update_session_selector(path: String) -> void:
	if session_option == null:
		return
	for index in range(SESSION_PRESETS.size()):
		var preset_path := str(SESSION_PRESETS[index].get("path", ""))
		if path == preset_path or path.ends_with(preset_path.trim_prefix("res://assets/processed_sessions/")):
			session_option.select(index)
			return


func _is_http_path(path: String) -> bool:
	return path.begins_with("http://") or path.begins_with("https://")


func _web_query_flag(key: String) -> bool:
	return _web_query_value(key).to_lower() in ["1", "true", "yes"]


func _web_query_value(key: String) -> String:
	if not OS.has_feature("web"):
		return ""
	var value: Variant = JavaScriptBridge.eval("new URLSearchParams(location.search).get('%s')" % key)
	return "" if value == null else str(value)


func _setup_web_bridge() -> void:
	if not OS.has_feature("web"):
		return
	var browser_window = JavaScriptBridge.get_interface("window")
	if browser_window == null:
		push_warning("Cannot expose SandStories Web bridge: window is unavailable")
		return
	web_command_callback = JavaScriptBridge.create_callback(_on_web_command)
	browser_window.__sandstoriesGodotCommand = web_command_callback


func _on_web_command(args: Array) -> void:
	if args.is_empty():
		return
	call_deferred("_handle_web_command", str(args[0]))


func _handle_web_command(raw_message: String) -> void:
	var parsed: Variant = JSON.parse_string(raw_message)
	if typeof(parsed) != TYPE_DICTIONARY:
		_emit_web_command_result("", false, {}, "Command must be a JSON object.")
		return
	var message: Dictionary = parsed
	var request_id := str(message.get("requestId", ""))
	var command := str(message.get("command", ""))
	var payload := {}
	var raw_payload: Variant = message.get("payload", {})
	if typeof(raw_payload) == TYPE_DICTIONARY:
		payload = raw_payload

	match command:
		"get_state":
			_emit_web_command_result(
				request_id,
				true,
				_web_state_snapshot()
			)
			return
		"set_playing":
			_set_playback_state(bool(payload.get("playing", true)))
		"toggle_playback":
			_set_playback_state(not is_playing)
		"seek":
			_seek_playhead(float(payload.get("seconds", playhead)))
		"seek_normalized":
			var progress: float = clampf(
				float(payload.get("progress", 0.0)),
				0.0,
				1.0
			)
			_seek_playhead(progress * duration)
		"load_session":
			var requested_path := str(payload.get("url", ""))
			if requested_path == "":
				_emit_web_command_result(
					request_id,
					false,
					{},
					"load_session requires payload.url."
				)
				return
			await _load_session(requested_path)
			if current_session_path != requested_path:
				_emit_web_command_result(
					request_id,
					false,
					{},
					"Session did not finish loading."
				)
				return
		"set_condition":
			var requested_condition := str(payload.get("condition", ""))
			var valid_conditions := [
				"baseline",
				"no_audio",
				"no_gestures",
				"no_objects",
				"no_sand",
				"stage2",
			]
			if requested_condition not in valid_conditions:
				_emit_web_command_result(
					request_id,
					false,
					{},
					"Unknown condition: " + requested_condition
				)
				return
			_on_experiment_condition_requested(requested_condition)
		"set_layer":
			var layer := str(payload.get("layer", ""))
			if layer not in [
				"sand",
				"heightmap_surface",
				"gestures",
				"objects",
				"audio",
				"annotations",
			]:
				_emit_web_command_result(
					request_id,
					false,
					{},
					"Unknown layer: " + layer
				)
				return
			var layer_visible := bool(payload.get("visible", true))
			_set_layer_visible(layer, layer_visible)
			_set_layer_toggle_value(layer, layer_visible)
			_log_event(
				"host_layer_toggle",
				{"layer": layer, "visible": layer_visible}
			)
		"set_surface_control":
			var control_key := str(payload.get("key", ""))
			if not surface_controls.has(control_key):
				_emit_web_command_result(
					request_id,
					false,
					{},
					"Unknown surface control: " + control_key
				)
				return
			var control_value := float(
				payload.get("value", surface_controls[control_key])
			)
			surface_controls[control_key] = control_value
			if surface_sliders.has(control_key):
				surface_sliders[control_key].set_value_no_signal(
					control_value
				)
			_apply_surface_controls()
			_log_event(
				"host_surface_control",
				{"key": control_key, "value": control_value}
			)
		"set_view":
			var preset := str(payload.get("preset", "orbit"))
			if preset not in ["top", "front", "orbit"]:
				_emit_web_command_result(
					request_id,
					false,
					{},
					"Unknown camera preset: " + preset
				)
				return
			_set_camera_preset(preset)
		"set_focus_mode":
			var requested_focus := bool(payload.get("enabled", true))
			if requested_focus != focus_mode:
				_toggle_focus_mode()
		"set_training_guide":
			var guide_mode := str(payload.get("mode", "off"))
			if guide_mode not in [
				"off",
				"playback",
				"camera",
				"layers",
				"occlusion",
				"segmentation",
				"referential",
			]:
				_emit_web_command_result(
					request_id,
					false,
					{},
					"Unknown training guide: " + guide_mode
				)
				return
			_set_training_guide(
				guide_mode,
				int(payload.get("step", 1)),
				int(payload.get("total", 3))
			)
		"mark_evidence":
			_on_mark_evidence_pressed()
		"record_host_event":
			_log_event("host_event", payload)
		_:
			_emit_web_command_result(
				request_id,
				false,
				{},
				"Unknown command: " + command
			)
			return

	_emit_web_command_result(request_id, true, _web_state_snapshot())
	_emit_web_state()


func _emit_web_command_result(
	request_id: String,
	ok: bool,
	data: Dictionary = {},
	error_message := ""
) -> void:
	_emit_web_message("command_result", {
		"requestId": request_id,
		"ok": ok,
		"data": data,
		"error": error_message,
	})


func _emit_web_state() -> void:
	_emit_web_message("state", _web_state_snapshot())


func _emit_web_message(kind: String, detail: Dictionary) -> void:
	if not OS.has_feature("web"):
		return
	var envelope := {
		"kind": kind,
		"detail": detail,
	}
	var encoded := Marshalls.raw_to_base64(
		JSON.stringify(envelope).to_utf8_buffer()
	)
	JavaScriptBridge.eval(
		"window.SandStories && window.SandStories.__receiveBase64('%s')" %
		encoded
	)


func _web_state_snapshot() -> Dictionary:
	var layers := {
		"sand": sand_layer != null and sand_layer.visible,
		"heightmap_surface": (
			heightmap_surface_node != null
			and heightmap_surface_node.visible
		),
		"gestures": gesture_layer != null and gesture_layer.visible,
		"objects": object_layer != null and object_layer.visible,
		"audio": audio_user_enabled,
		"annotations": (
			annotation_layer != null
			and annotation_layer.visible
		),
	}
	return {
		"ready": web_bridge_ready,
		"embedded": web_embed_mode,
		"playing": is_playing,
		"time": playhead,
		"duration": duration,
		"progress": playhead / duration if duration > 0.0 else 0.0,
		"sessionUrl": current_session_path,
		"sessionTitle": str(session.get("title", "")),
		"condition": current_condition,
		"trainingGuide": training_guide_mode,
		"layers": layers,
		"surface": surface_controls.duplicate(true),
		"frameIndex": surface_frame_index,
		"frameCount": processed_surface_frames.size(),
		"camera": {
			"yaw": camera_yaw,
			"pitch": camera_pitch,
			"distance": camera_distance,
			"target": [
				camera_target.x,
				camera_target.y,
				camera_target.z,
			],
		},
	}


func _should_autoplay_session(path: String) -> bool:
	if not _web_query_flag("autoplay"):
		return false
	var requested_session := _web_query_value("session")
	return requested_session == "" or requested_session == path


func _http_get(path: String) -> PackedByteArray:
	var request := HTTPRequest.new()
	add_child(request)
	var error := request.request(path)
	if error != OK:
		request.queue_free()
		push_error("HTTP request failed to start: " + path)
		return PackedByteArray()
	var result: Array = await request.request_completed
	request.queue_free()
	var response_code := int(result[1])
	if response_code < 200 or response_code >= 300:
		push_error("HTTP request failed %d: %s" % [response_code, path])
		return PackedByteArray()
	return result[3]


func _http_get_text(path: String) -> String:
	var body := await _http_get(path)
	if body.is_empty():
		return ""
	return body.get_string_from_utf8()


func _rebase_external_data_sources() -> void:
	for key in data_sources.keys():
		var value = data_sources[key]
		if typeof(value) == TYPE_STRING:
			data_sources[key] = _external_asset_path(str(value))


func _external_asset_path(path: String) -> String:
	if path == "" or _is_http_path(path) or path.begins_with("user://"):
		return path
	if external_session_base_dir == "":
		return path
	if path.begins_with("res://assets/processed_sessions/"):
		return external_session_base_dir.path_join(path.get_file())
	if not path.begins_with("res://"):
		return external_session_base_dir.path_join(path)
	return path


func _load_processed_surface_frames(generation: int) -> void:
	processed_surface_frames.clear()
	processed_surface_base_dir = ""
	surface_frame_index = -1
	surface_baseline_height_offset = 0.0

	var manifest_path := str(data_sources.get("processed_manifest", ""))
	if _is_http_path(manifest_path):
		await _load_remote_processed_surface_frames(manifest_path, generation)
		return
	if generation != session_load_generation:
		return
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

	_apply_processed_surface_manifest(parsed, manifest_path)


func _load_remote_processed_surface_frames(
	manifest_path: String,
	generation: int
) -> void:
	var text := await _http_get_text(manifest_path)
	if generation != session_load_generation or text == "":
		_update_surface_frame_ui()
		return
	var parsed = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		_update_surface_frame_ui()
		return
	_apply_processed_surface_manifest(parsed, manifest_path)


func _apply_processed_surface_manifest(parsed: Dictionary, manifest_path: String) -> void:
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

	var selected := 0
	for index in range(processed_surface_frames.size()):
		var frame: Dictionary = processed_surface_frames[index]
		if float(frame.get("time", 0.0)) <= playhead:
			selected = index
		else:
			break
	_set_surface_frame(selected, false)


func _load_external_hand_tracks(generation: int) -> void:
	var hand_tracks_path := str(data_sources.get("hand_tracks", ""))
	if hand_tracks_path == "":
		return
	var resolved_path := hand_tracks_path
	if not _is_http_path(resolved_path) and not resolved_path.begins_with("res://") and not resolved_path.begins_with("user://") and processed_surface_base_dir != "":
		resolved_path = processed_surface_base_dir.path_join(resolved_path)
	var parsed
	if _is_http_path(resolved_path):
		var text := await _http_get_text(resolved_path)
		if generation != session_load_generation or text == "":
			return
		parsed = JSON.parse_string(text)
	else:
		if not FileAccess.file_exists(resolved_path):
			return
		var file := FileAccess.open(resolved_path, FileAccess.READ)
		if file == null:
			return
		parsed = JSON.parse_string(file.get_as_text())
	if generation != session_load_generation:
		return
	if typeof(parsed) == TYPE_DICTIONARY:
		if parsed.has("hand_tracks"):
			session["hand_tracks"] = parsed.get("hand_tracks", [])
		elif parsed.has("mediapipe_hands"):
			session["mediapipe_hands"] = parsed.get("mediapipe_hands", [])
	elif typeof(parsed) == TYPE_ARRAY:
		session["hand_tracks"] = parsed


func _load_session_audio(generation: int) -> void:
	_dispose_audio_player()
	var audio_path := str(data_sources.get("audio", ""))
	if audio_path == "":
		_update_audio_toggle_state()
		return
	var stream: AudioStream
	if _is_http_path(audio_path):
		var body := await _http_get(audio_path)
		if generation != session_load_generation or body.is_empty():
			return
		var lower_path := audio_path.to_lower()
		if lower_path.ends_with(".ogg") or lower_path.ends_with(".oga"):
			stream = AudioStreamOggVorbis.load_from_buffer(body)
		elif lower_path.ends_with(".mp3"):
			stream = AudioStreamMP3.load_from_buffer(body)
		else:
			push_warning(
				"Remote narration must be OGG Vorbis or MP3: " + audio_path
			)
			return
	elif ResourceLoader.exists(audio_path):
		var loaded := load(audio_path)
		if loaded is AudioStream:
			stream = loaded
	if generation != session_load_generation or stream == null:
		_update_audio_toggle_state()
		return
	audio_player = AudioStreamPlayer.new()
	audio_player.name = "NarrationAudio"
	audio_player.stream = stream
	audio_player.autoplay = false
	add_child(audio_player)
	_update_audio_toggle_state()


func _dispose_audio_player() -> void:
	if audio_player == null:
		return
	audio_player.stop()
	audio_player.queue_free()
	audio_player = null


func _update_audio_toggle_state() -> void:
	if not layer_toggles.has("audio"):
		return
	var toggle: CheckBox = layer_toggles["audio"]
	toggle.disabled = audio_player == null
	if audio_player == null:
		toggle.set_pressed_no_signal(false)


func _sync_audio_playback(force_seek := false) -> void:
	if audio_player == null:
		return
	var should_play := (
		is_playing
		and audio_user_enabled
		and current_condition != "no_audio"
	)
	if not should_play:
		if audio_player.playing:
			audio_player.stream_paused = true
		return
	if not audio_player.playing:
		audio_player.play(playhead)
	else:
		audio_player.stream_paused = false
		if force_seek:
			audio_player.seek(playhead)


func _surface_frame_path(frame: Dictionary, key: String) -> String:
	var value := str(frame.get(key, ""))
	if value == "":
		return ""
	if _is_http_path(value) or value.begins_with("res://") or value.begins_with("user://"):
		return value
	if processed_surface_base_dir == "":
		return value
	return processed_surface_base_dir.path_join(value)


func _set_surface_frame(index: int, apply_now := true) -> bool:
	if processed_surface_frames.is_empty():
		surface_frame_index = -1
		_update_surface_frame_ui()
		return false
	var requested_index: int = clamp(index, 0, processed_surface_frames.size() - 1)
	if apply_now:
		_prefetch_surface_window(requested_index)
		if not _surface_frame_textures_ready(requested_index):
			surface_frame_pending_index = requested_index
			return false
	surface_frame_pending_index = -1
	surface_frame_index = requested_index
	var frame: Dictionary = processed_surface_frames[surface_frame_index]
	surface_baseline_height_offset = float(frame.get("baselineHeightCorrection", 0.0)) / 255.0
	var depth_key := "detailDepth" if frame.has("detailDepth") else "cleanDepth"
	var depth_path := _surface_frame_path(frame, depth_key)
	var texture_path := _surface_frame_path(frame, "cleanRgb")
	var occlusion_path := _surface_frame_path(frame, "occlusionMask")
	var overlay_path := _surface_frame_path(frame, "maskOverlay")
	var hand_overlay_path := _surface_frame_path(frame, "virtualHandOverlay")
	var hand_geometry_path := _surface_frame_path(frame, "virtualHandGeometry")
	var hand_mesh_path := _surface_frame_path(frame, "virtualHandMesh")
	if depth_path != "":
		data_sources["depth_map"] = depth_path
	if texture_path != "":
		data_sources["texture_map"] = texture_path
	if occlusion_path != "":
		data_sources["occlusion_mask"] = occlusion_path
	if overlay_path != "":
		data_sources["mask_overlay"] = overlay_path
	if hand_overlay_path != "":
		data_sources["virtual_hand_overlay"] = hand_overlay_path
	if hand_geometry_path != "":
		data_sources["virtual_hand_geometry"] = hand_geometry_path
	if hand_mesh_path != "":
		data_sources["virtual_hand_mesh"] = hand_mesh_path
	else:
		data_sources.erase("virtual_hand_mesh")
	if apply_now:
		_reload_static_surface_textures()
		_apply_surface_texture_source()
		_apply_mano_hand_mesh()
		_update_source_status()
		_log_event("surface_frame_selected", {
			"index": surface_frame_index + 1,
			"frameIndex": frame.get("frameIndex", surface_frame_index + 1),
			"time": frame.get("time", 0.0)
		})
		_prefetch_surface_window(surface_frame_index + 1)
		_trim_surface_texture_cache(surface_frame_index)
	_update_surface_frame_ui()
	return true


func _surface_frame_texture_paths(index: int) -> Array[String]:
	var paths: Array[String] = []
	if index < 0 or index >= processed_surface_frames.size():
		return paths
	var frame: Dictionary = processed_surface_frames[index]
	var depth_key := "detailDepth" if frame.has("detailDepth") else "cleanDepth"
	for key in [
		depth_key,
		"cleanRgb",
		"virtualHandOverlay",
		"virtualHandGeometry",
	]:
		var path := _surface_frame_path(frame, key)
		if path != "":
			paths.append(path)
	return paths


func _surface_frame_textures_ready(index: int) -> bool:
	for path in _surface_frame_texture_paths(index):
		if _is_http_path(path) and not surface_texture_cache.has(path):
			return false
	var mesh_path := _surface_frame_mesh_path(index)
	if (
		_is_http_path(mesh_path)
		and not mano_mesh_cache.has(mesh_path)
	):
		return false
	return true


func _surface_frame_mesh_path(index: int) -> String:
	if index < 0 or index >= processed_surface_frames.size():
		return ""
	var frame: Dictionary = processed_surface_frames[index]
	return _surface_frame_path(frame, "virtualHandMesh")


func _prefetch_surface_frame(index: int) -> void:
	for path in _surface_frame_texture_paths(index):
		_load_surface_texture(path)
	var mesh_path := _surface_frame_mesh_path(index)
	if mesh_path != "":
		_load_mano_mesh(mesh_path)


func _prefetch_surface_window(start_index: int) -> void:
	if processed_surface_frames.is_empty():
		return
	var first: int = clamp(start_index, 0, processed_surface_frames.size() - 1)
	var end: int = min(processed_surface_frames.size(), first + SURFACE_PREFETCH_AHEAD + 1)
	for index in range(first, end):
		_prefetch_surface_frame(index)


func _trim_surface_texture_cache(center_index: int) -> void:
	if processed_surface_frames.is_empty():
		return
	var keep: Dictionary = {}
	var first: int = max(0, center_index - SURFACE_CACHE_BEHIND)
	var end: int = min(
		processed_surface_frames.size(),
		center_index + SURFACE_PREFETCH_AHEAD + 1
	)
	for index in range(first, end):
		for path in _surface_frame_texture_paths(index):
			keep[path] = true
	var surface_mask_path := _source_path("surface_mask", "")
	if surface_mask_path != "":
		keep[surface_mask_path] = true
	for path in surface_texture_cache.keys():
		if not keep.has(path):
			surface_texture_cache.erase(path)
	var keep_meshes: Dictionary = {}
	for index in range(first, end):
		var mesh_path := _surface_frame_mesh_path(index)
		if mesh_path != "":
			keep_meshes[mesh_path] = true
	for path in mano_mesh_cache.keys():
		if not keep_meshes.has(path):
			mano_mesh_cache.erase(path)


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
			await _load_session(requested_session)
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


func _configure_experiment_mode() -> void:
	var requested_stage := _launch_value("study").to_lower()
	if requested_stage == "":
		return
	if requested_stage not in ["stage1", "stage2", "pilot"]:
		push_warning("Unknown study mode: " + requested_stage)
		return
	if experiment_runner == null:
		push_error("Experiment runner is unavailable")
		return
	var file := FileAccess.open(EXPERIMENT_PROTOCOL_PATH, FileAccess.READ)
	if file == null:
		push_error("Cannot open experiment protocol")
		return
	var parsed = JSON.parse_string(file.get_as_text())
	if typeof(parsed) != TYPE_DICTIONARY:
		push_error("Invalid experiment protocol JSON")
		return
	experiment_protocol = parsed
	experiment_mode = true
	experiment_stage = requested_stage
	_set_experiment_ui_mode()
	experiment_runner.configure(
		experiment_protocol,
		session,
		{
			"stage": experiment_stage,
			"participant": _launch_value("participant"),
			"condition": _launch_value("condition"),
		},
		_experiment_readiness()
	)
	_log_event("experiment_mode_enabled", {
		"stage": experiment_stage,
		"session": current_session_path,
	})


func _launch_value(key: String) -> String:
	var web_value := _web_query_value(key)
	if web_value != "":
		return web_value
	var prefix := "--%s=" % key
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with(prefix):
			return argument.trim_prefix(prefix)
	return ""


func _set_experiment_ui_mode() -> void:
	for control in researcher_controls:
		if control != null:
			control.visible = false
	if study_panel != null:
		study_panel.visible = false
	if experiment_runner != null:
		experiment_runner.visible = true
	if lower_dock_panel != null:
		lower_dock_panel.visible = false
	if reference_views_button != null:
		reference_views_button.visible = experiment_stage == "stage2"
	if experiment_stage != "stage2":
		reference_views_visible = false
		if fixed_views_panel != null:
			fixed_views_panel.visible = false
		_set_reference_viewports_active(false)
	_apply_experiment_condition_locks()


func _experiment_readiness() -> Dictionary:
	var has_sand: bool = (
		heightmap_surface_node != null
		or not processed_surface_frames.is_empty()
		or not session.get("surface_heights", []).is_empty()
	)
	var has_gestures: bool = (
		not hand_tracks.is_empty()
		or mano_hand_surface_node != null
		or str(data_sources.get("virtual_hand_mesh", "")) != ""
	)
	var has_objects: bool = not session.get("objects", []).is_empty()
	var has_audio: bool = audio_player != null
	var has_annotations: bool = (
		not session.get("surface_regions", []).is_empty()
		and not session.get("gesture_events", []).is_empty()
		and not session.get("references", []).is_empty()
	)
	var experiment: Dictionary = session.get("experiment", {})
	var has_validated_content: bool = bool(
		experiment.get("readyForDataCollection", false)
	)
	var warnings := []
	if not has_sand:
		warnings.append("No reconstructed sand modality.")
	if not has_gestures:
		warnings.append("No virtual-hand or gesture modality.")
	if not has_objects:
		warnings.append("No external-object modality.")
	if not has_audio:
		warnings.append("No narration audio; no-audio cannot be compared.")
	if experiment_stage == "stage2" and not has_annotations:
		warnings.append(
			"Stage 2 requires surface segments, gesture events, and references."
		)
	if not has_validated_content:
		warnings.append(
			"Creator-validated interpretation and questions are not marked ready."
		)
	var ready: bool = (
		has_sand
		and has_gestures
		and has_objects
		and has_audio
		and has_validated_content
		and (experiment_stage != "stage2" or has_annotations)
	)
	return {
		"ready": ready,
		"warnings": warnings,
		"modalities": {
			"sand": has_sand,
			"gestures": has_gestures,
			"objects": has_objects,
			"audio": has_audio,
			"annotations": has_annotations,
		},
	}


func _on_experiment_condition_requested(value: String) -> void:
	var valid := [
		"baseline",
		"no_audio",
		"no_gestures",
		"no_objects",
		"no_sand",
		"stage2",
	]
	if value not in valid:
		return
	current_condition = value
	if condition_option != null:
		condition_option.select(valid.find(value))
	_apply_condition(current_condition)
	_log_event("experiment_condition_applied", {"condition": value})


func _apply_experiment_condition_locks() -> void:
	if not experiment_mode:
		return
	for key in layer_toggles.keys():
		var toggle: CheckBox = layer_toggles[key]
		toggle.disabled = false
	if experiment_stage != "stage2" and layer_toggles.has("annotations"):
		layer_toggles["annotations"].disabled = true
	match current_condition:
		"no_audio":
			if layer_toggles.has("audio"):
				layer_toggles["audio"].disabled = true
		"no_gestures":
			if layer_toggles.has("gestures"):
				layer_toggles["gestures"].disabled = true
		"no_objects":
			if layer_toggles.has("objects"):
				layer_toggles["objects"].disabled = true
		"no_sand":
			if layer_toggles.has("sand"):
				layer_toggles["sand"].disabled = true
			if layer_toggles.has("heightmap_surface"):
				layer_toggles["heightmap_surface"].disabled = true
	if audio_player == null and layer_toggles.has("audio"):
		layer_toggles["audio"].disabled = true


func _on_experiment_evidence_requested(question_id: String) -> void:
	var snapshot := {
		"playhead": playhead,
		"cameraYaw": camera_yaw,
		"cameraPitch": camera_pitch,
		"cameraDistance": camera_distance,
		"cameraTarget": [
			camera_target.x,
			camera_target.y,
			camera_target.z,
		],
		"layers": {
			"sand": sand_layer.visible,
			"gestures": gesture_layer.visible,
			"objects": object_layer.visible,
			"audio": audio_user_enabled and current_condition != "no_audio",
			"annotations": annotation_layer.visible,
		},
	}
	experiment_runner.accept_evidence_snapshot(question_id, snapshot)
	_log_event("experiment_evidence_marked", {
		"question_id": question_id,
		"snapshot": snapshot,
	})


func _on_experiment_submission_ready(payload: Dictionary) -> void:
	var package := payload.duplicate(true)
	package["runtime"] = {
		"godotVersion": Engine.get_version_info().get("string", ""),
		"sessionPath": current_session_path,
		"interactionEvents": experiment_event_buffer.duplicate(true),
	}
	var absolute_dir := ProjectSettings.globalize_path(
		EXPERIMENT_SUBMISSION_DIR
	)
	var directory_error := DirAccess.make_dir_recursive_absolute(absolute_dir)
	if directory_error != OK:
		experiment_runner.set_export_status(
			"Could not create the local submission directory."
		)
		return
	var filename := "%s.json" % str(package.get("runId", "response"))
	var user_path := EXPERIMENT_SUBMISSION_DIR.path_join(filename)
	var output := FileAccess.open(user_path, FileAccess.WRITE)
	if output == null:
		experiment_runner.set_export_status(
			"Could not write the local response package."
		)
		return
	var json_text := JSON.stringify(package, "\t")
	output.store_string(json_text + "\n")
	output.close()
	if OS.has_feature("web"):
		_download_experiment_json(filename, json_text)
		experiment_runner.set_export_status(
			"Response package saved and browser download requested."
		)
	else:
		experiment_runner.set_export_status(
			"Response package saved to " + user_path
		)
	_log_event("experiment_submission_exported", {
		"run_id": package.get("runId", ""),
		"path": user_path,
	})


func _download_experiment_json(filename: String, json_text: String) -> void:
	var encoded := Marshalls.raw_to_base64(json_text.to_utf8_buffer())
	var script := """
		(() => {
			const binary = atob('%s');
			const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
			const blob = new Blob([bytes], {type: 'application/json'});
			const url = URL.createObjectURL(blob);
			const anchor = document.createElement('a');
			anchor.href = url;
			anchor.download = '%s';
			document.body.appendChild(anchor);
			anchor.click();
			anchor.remove();
			setTimeout(() => URL.revokeObjectURL(url), 1000);
		})()
	""" % [encoded, filename]
	JavaScriptBridge.eval(script)


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
	topdown_hand_surface_node = null
	topdown_hand_material = null
	mano_hand_surface_node = null
	mano_hand_material = null
	hand_tracks = _session_hand_tracks()
	hand_track_roots.clear()
	hand_model_nodes.clear()
	hand_joint_nodes.clear()
	hand_bone_nodes.clear()
	hand_virtual_nodes.clear()
	hand_rig_nodes.clear()
	hand_tool_nodes.clear()
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
	_build_topdown_hand_surface()
	_build_mano_hand_surface()

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
		var built_rigged_hand := false
		if bool(track.get("virtual_hand", true)):
			var visual_style := str(track.get("virtual_hand_style", "")).to_lower()
			if bool(track.get("use_rigged_hand", false)) or "humanoid" in visual_style:
				built_rigged_hand = _build_rigged_hand_for_track(root, track, color)
			if not built_rigged_hand:
				_build_virtual_hand_for_track(root, track_id, color)
		if bool(track.get("supports_tool_drawing", false)):
			_build_hand_tool_for_track(root, track_id)

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


func _build_rigged_hand_for_track(root: Node3D, track: Dictionary, color: Color) -> bool:
	var handedness := str(track.get("handedness", "right")).to_lower()
	if handedness not in ["left", "right"]:
		handedness = "right"
	var prefix := "Left" if handedness == "left" else "Right"
	var rig_path := HAND_RIG_LEFT_PATH if handedness == "left" else HAND_RIG_RIGHT_PATH
	if not ResourceLoader.exists(rig_path):
		return false
	var packed := load(rig_path)
	if not packed is PackedScene:
		return false
	var rig_root: Node3D = (packed as PackedScene).instantiate()
	rig_root.name = "%s_HumanoidGlassHand" % str(track.get("id", "hand"))
	root.add_child(rig_root)

	var skeleton := _find_hand_skeleton(rig_root)
	if skeleton == null:
		rig_root.queue_free()
		return false
	_style_rigged_hand_meshes(rig_root, color)

	var chain_specs := [
		{
			"bones": [
				prefix + "ThumbMetacarpal",
				prefix + "ThumbProximal",
				prefix + "ThumbDistal",
				prefix + "ThumbTip"
			],
			"points": [1, 2, 3, 4]
		},
		{
			"bones": [
				prefix + "IndexProximal",
				prefix + "IndexIntermediate",
				prefix + "IndexDistal",
				prefix + "IndexTip"
			],
			"points": [5, 6, 7, 8]
		},
		{
			"bones": [
				prefix + "MiddleProximal",
				prefix + "MiddleIntermediate",
				prefix + "MiddleDistal",
				prefix + "MiddleTip"
			],
			"points": [9, 10, 11, 12]
		},
		{
			"bones": [
				prefix + "RingProximal",
				prefix + "RingIntermediate",
				prefix + "RingDistal",
				prefix + "RingTip"
			],
			"points": [13, 14, 15, 16]
		},
		{
			"bones": [
				prefix + "LittleProximal",
				prefix + "LittleIntermediate",
				prefix + "LittleDistal",
				prefix + "LittleTip"
			],
			"points": [17, 18, 19, 20]
		}
	]
	var chains: Array = []
	for spec in chain_specs:
		var indices: Array[int] = []
		var valid := true
		for bone_name in spec["bones"]:
			var bone_index := skeleton.find_bone(str(bone_name))
			if bone_index < 0:
				valid = false
				break
			indices.append(bone_index)
		if valid:
			chains.append({"bones": indices, "points": spec["points"]})

	var wrist_index := skeleton.find_bone(prefix + "Hand")
	var index_mcp := skeleton.find_bone(prefix + "IndexProximal")
	var middle_mcp := skeleton.find_bone(prefix + "MiddleProximal")
	var ring_mcp := skeleton.find_bone(prefix + "RingProximal")
	var little_mcp := skeleton.find_bone(prefix + "LittleProximal")
	if (
		wrist_index < 0
		or index_mcp < 0
		or middle_mcp < 0
		or ring_mcp < 0
		or little_mcp < 0
		or chains.size() != 5
	):
		rig_root.queue_free()
		return false

	rig_root.visible = false
	var track_id := str(track.get("id", "hand"))
	hand_rig_nodes[track_id] = {
		"root": rig_root,
		"skeleton": skeleton,
		"chains": chains,
		"wrist": wrist_index,
		"palm_bones": [index_mcp, middle_mcp, ring_mcp, little_mcp],
		"palm_span_reference": float(
			track.get("rig_palm_span_reference", 0.0)
		),
		"palm_span_valid_min": float(
			track.get("rig_palm_span_valid_min", 0.0)
		),
		"palm_span_valid_max": float(
			track.get("rig_palm_span_valid_max", 0.0)
		),
		"max_orientation_step": deg_to_rad(float(
			track.get("rig_max_orientation_step_degrees", 42.0)
		)),
		"path": rig_path
	}
	return true


func _find_hand_skeleton(node: Node) -> Skeleton3D:
	if node is Skeleton3D:
		return node as Skeleton3D
	for child in node.get_children():
		var found := _find_hand_skeleton(child)
		if found != null:
			return found
	return null


func _style_rigged_hand_meshes(node: Node, color: Color) -> void:
	if node is MeshInstance3D:
		var mesh_node := node as MeshInstance3D
		mesh_node.material_override = _hologram_material(color, 0.84, 0.4)
		mesh_node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	for child in node.get_children():
		_style_rigged_hand_meshes(child, color)


func _build_hand_tool_for_track(root: Node3D, track_id: String) -> void:
	var tool_root := Node3D.new()
	tool_root.name = track_id + "_DrawingRod"
	root.add_child(tool_root)

	var shaft := MeshInstance3D.new()
	shaft.name = track_id + "_RodShaft"
	var shaft_mesh := CylinderMesh.new()
	shaft_mesh.height = 1.0
	shaft_mesh.top_radius = 0.020
	shaft_mesh.bottom_radius = 0.020
	shaft_mesh.radial_segments = 14
	shaft_mesh.rings = 1
	shaft.mesh = shaft_mesh
	shaft.material_override = _material(
		Color("#76563f"),
		0.58
	)
	shaft.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	tool_root.add_child(shaft)

	var tip := MeshInstance3D.new()
	tip.name = track_id + "_RodTip"
	var tip_mesh := CylinderMesh.new()
	tip_mesh.height = 1.0
	tip_mesh.top_radius = 0.020
	tip_mesh.bottom_radius = 0.006
	tip_mesh.radial_segments = 14
	tip_mesh.rings = 1
	tip.mesh = tip_mesh
	tip.material_override = _material(
		Color("#332d29"),
		0.38
	)
	tip.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	tool_root.add_child(tip)

	var end_cap := MeshInstance3D.new()
	end_cap.name = track_id + "_RodEnd"
	var end_mesh := SphereMesh.new()
	end_mesh.radius = 0.021
	end_mesh.height = 0.042
	end_mesh.radial_segments = 14
	end_mesh.rings = 7
	end_cap.mesh = end_mesh
	end_cap.material_override = shaft.material_override
	end_cap.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	tool_root.add_child(end_cap)

	tool_root.visible = false
	hand_tool_nodes[track_id] = {
		"root": tool_root,
		"shaft": shaft,
		"tip": tip,
		"end": end_cap
	}


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
	palm.material_override = _hologram_material(color, 0.46, 1.0)
	virtual_root.add_child(palm)

	var palm_volume := MeshInstance3D.new()
	palm_volume.name = track_id + "_PalmVolume"
	var palm_sphere := SphereMesh.new()
	palm_sphere.radius = 0.5
	palm_sphere.height = 1.0
	palm_sphere.radial_segments = 18
	palm_sphere.rings = 9
	palm_volume.mesh = palm_sphere
	palm_volume.material_override = _hologram_material(color, 0.76, 0.82)
	virtual_root.add_child(palm_volume)

	var segments: Array[MeshInstance3D] = []
	for segment_index in range(VIRTUAL_HAND_SEGMENTS.size()):
		var segment := MeshInstance3D.new()
		segment.name = "%s_SoftSegment%d" % [track_id, segment_index]
		var capsule := CapsuleMesh.new()
		capsule.height = 0.18
		capsule.radius = _virtual_segment_radius(segment_index)
		capsule.radial_segments = 12
		capsule.rings = 4
		segment.mesh = capsule
		segment.material_override = _hologram_material(color, 0.75, float(segment_index) * 0.07)
		virtual_root.add_child(segment)
		segments.append(segment)

	var tips: Array[MeshInstance3D] = []
	for tip_index in range(VIRTUAL_HAND_TIPS.size()):
		var tip := MeshInstance3D.new()
		tip.name = "%s_SoftTip%d" % [track_id, tip_index]
		var sphere := SphereMesh.new()
		var tip_radius := _virtual_joint_radius(int(VIRTUAL_HAND_TIPS[tip_index])) * 0.92
		sphere.radius = tip_radius
		sphere.height = tip_radius * 2.0
		sphere.radial_segments = 12
		sphere.rings = 6
		tip.mesh = sphere
		tip.material_override = _hologram_material(color.lightened(0.04), 0.82, 0.5 + float(tip_index) * 0.11)
		virtual_root.add_child(tip)
		tips.append(tip)

	var knuckles: Array[MeshInstance3D] = []
	for joint_index in VIRTUAL_HAND_KNUCKLES:
		var knuckle := MeshInstance3D.new()
		knuckle.name = "%s_SoftKnuckle%d" % [track_id, int(joint_index)]
		var sphere := SphereMesh.new()
		var joint_radius := _virtual_joint_radius(int(joint_index))
		sphere.radius = joint_radius
		sphere.height = joint_radius * 2.0
		sphere.radial_segments = 12
		sphere.rings = 6
		knuckle.mesh = sphere
		knuckle.material_override = _hologram_material(color, 0.72, float(joint_index) * 0.05)
		virtual_root.add_child(knuckle)
		knuckles.append(knuckle)

	var wrist := MeshInstance3D.new()
	wrist.name = track_id + "_SoftWrist"
	var wrist_capsule := CapsuleMesh.new()
	wrist_capsule.height = 0.24
	wrist_capsule.radius = 0.080
	wrist_capsule.radial_segments = 14
	wrist_capsule.rings = 5
	wrist.mesh = wrist_capsule
	wrist.material_override = _hologram_material(color.darkened(0.04), 0.66, 0.35)
	virtual_root.add_child(wrist)

	hand_virtual_nodes[track_id] = {
		"root": virtual_root,
		"palm": palm,
		"palm_volume": palm_volume,
		"segments": segments,
		"tips": tips,
		"knuckles": knuckles,
		"wrist": wrist
	}


func _virtual_segment_radius(segment_index: int) -> float:
	if segment_index >= VIRTUAL_HAND_SEGMENTS.size():
		return 0.03
	var connection: Array = VIRTUAL_HAND_SEGMENTS[segment_index]
	var a := int(connection[0])
	var b := int(connection[1])
	if a == 0:
		return 0.060
	if b in VIRTUAL_HAND_TIPS:
		return 0.035 if b == 20 else 0.038
	if a in [5, 9, 13, 17]:
		return 0.044 if a == 17 else 0.050
	return 0.039 if b in [3, 7, 11, 15, 19] else 0.043


func _virtual_joint_radius(index: int) -> float:
	if index == 0:
		return 0.075
	if index in [5, 9, 13]:
		return 0.058
	if index == 17:
		return 0.053
	if index in VIRTUAL_HAND_TIPS:
		return 0.038
	return 0.046


func _hologram_material(color: Color, alpha: float, pulse_offset: float) -> Material:
	if ResourceLoader.exists(HAND_HOLOGRAM_SHADER_PATH):
		var shader := load(HAND_HOLOGRAM_SHADER_PATH)
		if shader is Shader:
			var material := ShaderMaterial.new()
			material.shader = shader
			material.set_shader_parameter("core_color", Color(color.r, color.g, color.b, alpha))
			material.set_shader_parameter("alpha", alpha)
			material.set_shader_parameter("pulse_speed", 0.18 + pulse_offset * 0.018)
			material.set_shader_parameter("pulse_offset", pulse_offset)
			material.set_shader_parameter("scanline_strength", 0.018)
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


func _build_topdown_hand_surface() -> void:
	if str(data_sources.get("virtual_hand_overlay", "")) == "":
		return
	var material := _topdown_hand_overlay_material()
	if material == null:
		return
	topdown_hand_material = material
	var plane := PlaneMesh.new()
	plane.size = Vector2(5.5, 5.5)
	var subdivisions := (
		512
		if bool(data_sources.get("virtual_hand_measured_shell_v2", false))
		else (
			384
			if str(data_sources.get("virtual_hand_geometry", "")) != ""
			else 256
		)
	)
	plane.subdivide_width = subdivisions
	plane.subdivide_depth = subdivisions
	topdown_hand_surface_node = MeshInstance3D.new()
	topdown_hand_surface_node.name = "TopdownVirtualHandSurface"
	topdown_hand_surface_node.mesh = plane
	topdown_hand_surface_node.material_override = material
	gesture_layer.add_child(topdown_hand_surface_node)


func _build_mano_hand_surface() -> void:
	var has_mesh := str(data_sources.get("virtual_hand_mesh", "")) != ""
	if not has_mesh:
		for frame in processed_surface_frames:
			if (
				typeof(frame) == TYPE_DICTIONARY
				and str(frame.get("virtualHandMesh", "")) != ""
			):
				has_mesh = true
				break
	if not has_mesh:
		return

	mano_hand_material = _mano_hand_surface_material()
	if mano_hand_material == null:
		return

	mano_hand_surface_node = MeshInstance3D.new()
	mano_hand_surface_node.name = "ManoRgbdHandSurface"
	mano_hand_surface_node.material_override = mano_hand_material
	mano_hand_surface_node.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	mano_hand_surface_node.visible = false
	gesture_layer.add_child(mano_hand_surface_node)
	_apply_mano_hand_mesh()


func _mano_hand_surface_material() -> Material:
	var sequence: Dictionary = session.get("mano_rgbd_full_sequence", {})
	var preset := str(sequence.get("materialPreset", "warm_skin_pbr_v1"))
	if preset == "soft_peach_porcelain_v1":
		var shader := load(MANO_HAND_BEAUTY_SHADER_PATH)
		if shader is Shader:
			var parameters: Dictionary = sequence.get("materialParameters", {})
			var material := ShaderMaterial.new()
			material.shader = shader
			material.set_shader_parameter(
				"base_color",
				Color(str(parameters.get("baseColor", "#f3b49e")))
			)
			material.set_shader_parameter(
				"shadow_color",
				Color(str(parameters.get("shadowColor", "#b96f67")))
			)
			material.set_shader_parameter(
				"highlight_color",
				Color(str(parameters.get("highlightColor", "#ffe2d1")))
			)
			material.set_shader_parameter(
				"rim_color",
				Color(str(parameters.get("rimColor", "#ffede2")))
			)
			material.set_shader_parameter(
				"rim_strength",
				float(parameters.get("rimStrength", 0.32))
			)
			material.set_shader_parameter(
				"emission_strength",
				float(parameters.get("emissionStrength", 0.035))
			)
			material.set_shader_parameter(
				"roughness",
				float(parameters.get("roughness", 0.72))
			)
			return material

	var fallback := StandardMaterial3D.new()
	fallback.albedo_color = Color("#dfad98")
	fallback.roughness = 0.76
	fallback.metallic = 0.0
	fallback.emission_enabled = true
	fallback.emission = Color("#c98570")
	fallback.emission_energy_multiplier = 0.24
	fallback.cull_mode = BaseMaterial3D.CULL_DISABLED
	fallback.depth_draw_mode = BaseMaterial3D.DEPTH_DRAW_OPAQUE_ONLY
	return fallback


func _build_surface_video_players() -> void:
	_dispose_surface_video_players()
	var depth_video_path := str(data_sources.get("depth_video", ""))
	var texture_video_path := str(data_sources.get("texture_video", ""))
	if depth_video_path != "":
		depth_video_player = _build_video_player(depth_video_path)
	if texture_video_path != "":
		texture_video_player = _build_video_player(texture_video_path)
	var video_pair_available := (
		depth_video_player != null and texture_video_player != null
	)
	if not video_pair_available:
		use_video_streams = false
	if video_stream_toggle != null:
		video_stream_toggle.disabled = not video_pair_available
		video_stream_toggle.set_pressed_no_signal(use_video_streams)
	_apply_surface_texture_source()
	_set_surface_stream_playing(is_playing and use_video_streams)


func _dispose_surface_video_players() -> void:
	for player in [depth_video_player, texture_video_player]:
		if player == null:
			continue
		player.stop()
		player.queue_free()
	depth_video_player = null
	texture_video_player = null


func _build_video_player(path: String) -> VideoStreamPlayer:
	if not ResourceLoader.exists(path):
		return null

	var stream := load(path)
	if stream == null:
		return null

	var player := VideoStreamPlayer.new()
	player.stream = stream
	player.autoplay = false
	player.loop = true
	player.volume_db = -80.0
	player.visible = false
	player.mouse_filter = Control.MOUSE_FILTER_IGNORE
	player.position = Vector2(-10000, -10000)
	player.size = Vector2.ZERO
	add_child(player)
	return player


func _apply_surface_texture_source() -> void:
	if heightmap_material == null:
		return
	heightmap_material.set_shader_parameter("baseline_height_offset", surface_baseline_height_offset)
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
	_apply_topdown_hand_texture_source()


func _apply_topdown_hand_texture_source() -> void:
	if topdown_hand_material == null:
		return
	topdown_hand_material.set_shader_parameter(
		"baseline_height_offset",
		surface_baseline_height_offset
	)
	if static_depth_texture != null:
		topdown_hand_material.set_shader_parameter(
			"depth_map",
			static_depth_texture
		)
	if static_topdown_hand_texture != null:
		topdown_hand_material.set_shader_parameter(
			"hand_overlay",
			static_topdown_hand_texture
		)
	if static_topdown_hand_geometry_texture != null:
		topdown_hand_material.set_shader_parameter(
			"hand_geometry",
			static_topdown_hand_geometry_texture
		)


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
	_update_surface_frame_from_time()
	_update_hand()
	_update_annotations()
	_update_highlights()
	_update_referential_links()
	_update_active_gesture()
	time_label.text = "%.2f / %.2f" % [playhead, duration]


func _update_surface_frame_from_time() -> void:
	if processed_surface_frames.size() <= 1:
		return
	var target_index := 0
	for index in range(processed_surface_frames.size()):
		var frame: Dictionary = processed_surface_frames[index]
		if float(frame.get("time", 0.0)) <= playhead:
			target_index = index
		else:
			break
	if is_playing and surface_frame_index >= 0:
		target_index = min(target_index, surface_frame_index + 1)
	if target_index != surface_frame_index:
		if not _set_surface_frame(target_index) and is_playing and surface_frame_index >= 0:
			var displayed_frame: Dictionary = processed_surface_frames[surface_frame_index]
			playhead = float(displayed_frame.get("time", playhead))
			time_slider.set_value_no_signal(playhead)


func _update_hand() -> void:
	for track in hand_tracks:
		if typeof(track) != TYPE_DICTIONARY:
			continue
		var track_id := str(track.get("id", "hand"))
		if not hand_joint_nodes.has(track_id):
			continue
		var samples: Array = track.get("samples", [])
		var points := _sample_points(track, samples, playhead)
		var sample_state := _sample_hand_state(track, samples, playhead)
		var intent := str(sample_state.get("intent", "positioning"))
		var tool_contact: Variant = _sample_optional_sample_point(
			track,
			samples,
			playhead,
			"toolContactPoint"
		)
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
		_update_rigged_hand(track_id, points, bool(track.get("virtual_hand", true)))
		_update_virtual_hand(track_id, points, bool(track.get("virtual_hand", true)))
		_update_hand_tool(track_id, points, intent, tool_contact)
		_update_hand_model(track_id, points, centre, visible_joint_count, track)


func _sample_points(track: Dictionary, samples: Array, time: float) -> Array[Vector3]:
	var points: Array[Vector3] = []
	if samples.is_empty():
		return points
	if samples.size() == 1:
		return _points_from_sample(samples[0])

	var first_time := float(samples[0].get("time", 0.0))
	var last_time := float(samples[samples.size() - 1].get("time", first_time))
	var endpoint_hold := float(track.get("endpoint_hold_seconds", 0.05))
	if time < first_time - endpoint_hold or time > last_time + endpoint_hold:
		return points

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
	var max_gap_seconds := float(track.get("max_gap_seconds", 0.24))
	if span > max_gap_seconds:
		return points
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


func _sample_hand_state(
	track: Dictionary,
	samples: Array,
	time: float
) -> Dictionary:
	if samples.is_empty():
		return {}
	var first_time := float(samples[0].get("time", 0.0))
	var last_time := float(
		samples[samples.size() - 1].get("time", first_time)
	)
	var endpoint_hold := float(track.get("endpoint_hold_seconds", 0.05))
	if time < first_time - endpoint_hold or time > last_time + endpoint_hold:
		return {}
	var bracket := _sample_bracket(samples, time)
	var left_index := int(bracket.get("left", 0))
	var right_index := int(bracket.get("right", left_index))
	var left_sample: Dictionary = samples[left_index]
	var right_sample: Dictionary = samples[right_index]
	var left_time := float(left_sample.get("time", 0.0))
	var right_time := float(right_sample.get("time", left_time))
	if right_time - left_time > float(track.get("max_gap_seconds", 0.24)):
		return {}
	if abs(time - left_time) <= abs(right_time - time):
		return left_sample
	return right_sample


func _sample_optional_sample_point(
	track: Dictionary,
	samples: Array,
	time: float,
	field: String
) -> Variant:
	if samples.is_empty():
		return null
	var state := _sample_hand_state(track, samples, time)
	if state.is_empty() or not state.has(field):
		return null
	var bracket := _sample_bracket(samples, time)
	var left_sample: Dictionary = samples[int(bracket.get("left", 0))]
	var right_sample: Dictionary = samples[int(bracket.get("right", 0))]
	if not left_sample.has(field) or not right_sample.has(field):
		return _array_to_vec3(state.get(field, [0.0, 0.0, 0.0]))
	var left_time := float(left_sample.get("time", 0.0))
	var right_time := float(right_sample.get("time", left_time))
	var span: float = max(0.0001, right_time - left_time)
	var t: float = clamp((time - left_time) / span, 0.0, 1.0)
	var smooth_t: float = t * t * (3.0 - 2.0 * t)
	return _array_to_vec3(left_sample[field]).lerp(
		_array_to_vec3(right_sample[field]),
		smooth_t
	)


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


func _update_rigged_hand(track_id: String, points: Array[Vector3], enabled: bool) -> void:
	if not hand_rig_nodes.has(track_id):
		return
	var rig: Dictionary = hand_rig_nodes[track_id]
	var rig_root: Node3D = rig.get("root", null)
	var skeleton: Skeleton3D = rig.get("skeleton", null)
	if rig_root == null or skeleton == null:
		return
	rig_root.visible = enabled and points.size() >= 21
	if not rig_root.visible:
		skeleton.clear_bones_global_pose_override()
		hand_rendered_points.erase(track_id)
		return

	var palm_bones: Array = rig.get("palm_bones", [])
	if palm_bones.size() < 4:
		rig_root.visible = false
		return
	var wrist_rest := skeleton.get_bone_global_rest(int(rig.get("wrist", 0))).origin
	var index_rest := skeleton.get_bone_global_rest(int(palm_bones[0])).origin
	var middle_rest := skeleton.get_bone_global_rest(int(palm_bones[1])).origin
	var ring_rest := skeleton.get_bone_global_rest(int(palm_bones[2])).origin
	var little_rest := skeleton.get_bone_global_rest(int(palm_bones[3])).origin
	var rest_knuckle_centre := (index_rest + middle_rest + ring_rest + little_rest) * 0.25
	var target_knuckle_centre := (points[5] + points[9] + points[13] + points[17]) * 0.25
	var rest_basis := _hand_palm_basis(
		index_rest - little_rest,
		rest_knuckle_centre - wrist_rest
	)
	var target_width := points[5] - points[17]
	var target_length := target_knuckle_centre - points[0]
	var target_basis := _hand_palm_basis(target_width, target_length)
	var rest_span := index_rest.distance_to(little_rest)
	var target_span := points[5].distance_to(points[17])
	if rest_span < 0.001 or target_span < 0.001:
		rig_root.visible = false
		return
	var span_reference := float(
		rig.get("palm_span_reference", 0.0)
	)
	if span_reference > 0.001:
		var minimum_valid_span := float(
			rig.get("palm_span_valid_min", span_reference * 0.35)
		)
		var maximum_valid_span := float(
			rig.get("palm_span_valid_max", span_reference * 1.75)
		)
		if minimum_valid_span <= 0.001:
			minimum_valid_span = span_reference * 0.35
		if maximum_valid_span <= minimum_valid_span:
			maximum_valid_span = span_reference * 1.75
		var width_axis := target_width.normalized()
		var palm_length_orthogonal := (
			target_length
			- width_axis * target_length.dot(width_axis)
		).length()
		var target_basis_valid := (
			target_span >= minimum_valid_span
			and target_span <= maximum_valid_span
			and palm_length_orthogonal >= span_reference * 0.24
		)
		if target_basis_valid and rig.has("last_valid_target_basis"):
			var last_basis: Basis = rig["last_valid_target_basis"]
			var orientation_step := (
				last_basis.get_rotation_quaternion().angle_to(
					target_basis.get_rotation_quaternion()
				)
			)
			target_basis_valid = orientation_step <= float(
				rig.get("max_orientation_step", deg_to_rad(42.0))
			)
		if target_basis_valid:
			rig["last_valid_target_basis"] = target_basis
		elif rig.has("last_valid_target_basis"):
			target_basis = rig["last_valid_target_basis"]
		else:
			rig_root.visible = false
			return
	else:
		span_reference = target_span
	var hand_scale: float = clamp(
		span_reference / rest_span,
		0.35,
		8.0
	)
	var rotation := target_basis * rest_basis.inverse()
	rig_root.transform = Transform3D(
		rotation.scaled(Vector3.ONE * hand_scale),
		points[0] - rotation * (wrist_rest * hand_scale)
	)

	var inverse_rig := rig_root.transform.affine_inverse()
	var local_points: Array[Vector3] = []
	for point in points:
		local_points.append(inverse_rig * point)
	skeleton.clear_bones_global_pose_override()
	for chain in rig.get("chains", []):
		_pose_rigged_finger(skeleton, chain, local_points)
	hand_rendered_points[track_id] = points


func _update_hand_tool(
	track_id: String,
	points: Array[Vector3],
	intent: String,
	tool_contact: Variant
) -> void:
	if not hand_tool_nodes.has(track_id):
		return
	var tool: Dictionary = hand_tool_nodes[track_id]
	var tool_root: Node3D = tool.get("root", null)
	if tool_root == null:
		return
	tool_root.visible = (
		intent == "tool_drawing"
		and points.size() >= 21
		and tool_contact is Vector3
	)
	if not tool_root.visible:
		return

	var contact := tool_contact as Vector3
	var grip := (points[4] + points[6] + points[10]) / 3.0
	var direction := grip - contact
	if direction.length() < 0.12:
		var palm_centre := (
			points[0]
			+ points[5]
			+ points[9]
			+ points[13]
			+ points[17]
		) / 5.0
		direction = palm_centre - contact
	if direction.length() < 0.12:
		direction = Vector3(0.35, 0.32, 0.0)
	var axis := direction.normalized()
	var rod_length: float = max(direction.length() + 0.20, 0.62)
	var tip_length := 0.085
	var rod_end := contact + axis * rod_length
	var tip_end := contact + axis * tip_length

	var shaft: MeshInstance3D = tool.get("shaft", null)
	var tip: MeshInstance3D = tool.get("tip", null)
	var end_cap: MeshInstance3D = tool.get("end", null)
	if shaft != null:
		_place_bone_between(shaft, tip_end * 0.92 + contact * 0.08, rod_end)
		shaft.visible = true
	if tip != null:
		_place_bone_between(tip, contact, tip_end)
		tip.visible = true
	if end_cap != null:
		end_cap.position = rod_end
		end_cap.visible = true


func _hand_palm_basis(width: Vector3, length: Vector3) -> Basis:
	var x_axis := width.normalized()
	var z_axis := (length - x_axis * length.dot(x_axis)).normalized()
	if z_axis.length() < 0.001:
		z_axis = Vector3.FORWARD
	var y_axis := z_axis.cross(x_axis).normalized()
	return Basis(x_axis, y_axis, z_axis).orthonormalized()


func _pose_rigged_finger(
	skeleton: Skeleton3D,
	chain: Dictionary,
	points: Array[Vector3]
) -> void:
	var bones: Array = chain.get("bones", [])
	var landmarks: Array = chain.get("points", [])
	if bones.size() != landmarks.size() or bones.size() < 2:
		return
	for segment_index in range(bones.size() - 1):
		var bone_index := int(bones[segment_index])
		var next_bone_index := int(bones[segment_index + 1])
		var point_index := int(landmarks[segment_index])
		var next_point_index := int(landmarks[segment_index + 1])
		if point_index >= points.size() or next_point_index >= points.size():
			return
		var current := skeleton.get_bone_global_pose(bone_index)
		var current_next := skeleton.get_bone_global_pose(next_bone_index)
		var current_direction := current_next.origin - current.origin
		var target_direction := points[next_point_index] - points[point_index]
		if current_direction.length() < 0.0001 or target_direction.length() < 0.0001:
			continue
		var target_length_ratio := (
			target_direction.length() / current_direction.length()
		)
		if target_length_ratio < 0.28 or target_length_ratio > 2.6:
			continue
		var align := Quaternion(
			current_direction.normalized(),
			target_direction.normalized()
		)
		var align_angle := align.get_angle()
		var maximum_swing := deg_to_rad(
			82.0 if segment_index == 0 else 74.0
		)
		if align_angle > maximum_swing:
			align = Quaternion.IDENTITY.slerp(
				align,
				maximum_swing / align_angle
			)
		var target_global_basis := Basis(align) * current.basis
		skeleton.set_bone_global_pose_override(
			bone_index,
			Transform3D(target_global_basis, current.origin),
			1.0,
			true
		)
		skeleton.force_update_all_bone_transforms()


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

	var palm_volume: MeshInstance3D = virtual_hand.get("palm_volume", null)
	if palm_volume != null:
		_update_virtual_palm_volume(palm_volume, points)

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
			_place_capsule_between(segment, points[a], points[b])

	var tips: Array = virtual_hand.get("tips", [])
	for i in range(tips.size()):
		var tip: MeshInstance3D = tips[i]
		var tip_point := int(VIRTUAL_HAND_TIPS[i])
		tip.visible = tip_point < points.size()
		if tip.visible:
			tip.position = points[tip_point]

	var knuckles: Array = virtual_hand.get("knuckles", [])
	for i in range(knuckles.size()):
		var knuckle: MeshInstance3D = knuckles[i]
		var joint_point := int(VIRTUAL_HAND_KNUCKLES[i])
		knuckle.visible = joint_point < points.size()
		if knuckle.visible:
			knuckle.position = points[joint_point]

	var wrist: MeshInstance3D = virtual_hand.get("wrist", null)
	if wrist != null:
		var palm_centre := (points[5] + points[9] + points[13] + points[17]) * 0.25
		var wrist_direction := points[0] - palm_centre
		if wrist_direction.length() > 0.001:
			var wrist_length: float = clamp(points[5].distance_to(points[17]) * 0.48, 0.16, 0.32)
			_place_capsule_between(wrist, points[0], points[0] + wrist_direction.normalized() * wrist_length)
			wrist.visible = true
		else:
			wrist.visible = false


func _update_virtual_palm_volume(palm_volume: MeshInstance3D, points: Array[Vector3]) -> void:
	if points.size() < 18:
		palm_volume.visible = false
		return
	var knuckle_centre := (points[5] + points[9] + points[13] + points[17]) * 0.25
	var length_axis := knuckle_centre - points[0]
	var width_axis := points[5] - points[17]
	if length_axis.length() < 0.001 or width_axis.length() < 0.001:
		palm_volume.visible = false
		return

	var x_axis := width_axis.normalized()
	var z_axis := (length_axis - x_axis * length_axis.dot(x_axis)).normalized()
	if z_axis.length() < 0.001:
		palm_volume.visible = false
		return
	var y_axis := z_axis.cross(x_axis).normalized()
	var palm_span := width_axis.length()
	var palm_length := length_axis.length()
	palm_volume.position = points[0].lerp(knuckle_centre, 0.54)
	palm_volume.basis = Basis(x_axis, y_axis, z_axis).scaled(
		Vector3(
			clamp(palm_span * 0.90, 0.24, 0.54),
			clamp(palm_span * 0.18, 0.055, 0.105),
			clamp(palm_length * 0.88, 0.28, 0.62)
		)
	)
	palm_volume.visible = true


func _make_hand_palm_mesh(points: Array[Vector3]) -> ArrayMesh:
	var surface_tool := SurfaceTool.new()
	surface_tool.begin(Mesh.PRIMITIVE_TRIANGLES)
	if points.size() < 18:
		return surface_tool.commit()

	var palm_normal := (points[5] - points[0]).cross(points[17] - points[0]).normalized()
	if palm_normal.length() < 0.001:
		palm_normal = Vector3.UP
	if palm_normal.y < 0.0:
		palm_normal = -palm_normal
	var palm_span := points[5].distance_to(points[17])
	var thickness: float = clamp(palm_span * 0.13, 0.040, 0.072)
	var half_offset := palm_normal * thickness * 0.5

	for triangle in HAND_PALM_TRIANGLES:
		var a_index := int(triangle[0])
		var b_index := int(triangle[1])
		var c_index := int(triangle[2])
		var a := points[a_index] + half_offset
		var b := points[b_index] + half_offset
		var c := points[c_index] + half_offset
		_add_hand_triangle(surface_tool, a, b, c)
		_add_hand_triangle(
			surface_tool,
			points[c_index] - half_offset,
			points[b_index] - half_offset,
			points[a_index] - half_offset
		)

	for outline_index in range(VIRTUAL_HAND_PALM_OUTLINE.size()):
		var next_index := (outline_index + 1) % VIRTUAL_HAND_PALM_OUTLINE.size()
		var point_a := points[int(VIRTUAL_HAND_PALM_OUTLINE[outline_index])]
		var point_b := points[int(VIRTUAL_HAND_PALM_OUTLINE[next_index])]
		var front_a := point_a + half_offset
		var front_b := point_b + half_offset
		var back_a := point_a - half_offset
		var back_b := point_b - half_offset
		_add_hand_triangle(surface_tool, front_a, back_a, back_b)
		_add_hand_triangle(surface_tool, front_a, back_b, front_b)
	return surface_tool.commit()


func _add_hand_triangle(surface_tool: SurfaceTool, a: Vector3, b: Vector3, c: Vector3) -> void:
	var normal := (b - a).cross(c - a).normalized()
	surface_tool.set_normal(normal)
	surface_tool.add_vertex(a)
	surface_tool.set_normal(normal)
	surface_tool.add_vertex(b)
	surface_tool.set_normal(normal)
	surface_tool.add_vertex(c)


func _place_capsule_between(capsule_node: MeshInstance3D, a: Vector3, b: Vector3) -> void:
	var delta := b - a
	var length := delta.length()
	if length < 0.001:
		capsule_node.visible = false
		return
	var capsule := capsule_node.mesh as CapsuleMesh
	if capsule == null:
		_place_bone_between(capsule_node, a, b)
		return

	capsule.height = max(length, capsule.radius * 2.0)
	var y_axis := delta / length
	var helper := Vector3.RIGHT if abs(y_axis.dot(Vector3.UP)) > 0.96 else Vector3.UP
	var x_axis := helper.cross(y_axis).normalized()
	var z_axis := x_axis.cross(y_axis).normalized()
	capsule_node.transform = Transform3D(Basis(x_axis, y_axis, z_axis), (a + b) * 0.5)


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
	var next_event_time := -1.0
	var next_event_label := ""
	for event in session.get("gesture_events", []):
		var start := float(event.get("start", 0.0))
		var end := float(event.get("end", duration))
		if playhead >= start and playhead <= end:
			active = "%s -> %s" % [str(event.get("label", event.get("kind", "gesture"))), str(event.get("target", ""))]
			break
		if start > playhead and (next_event_time < 0.0 or start < next_event_time):
			next_event_time = start
			next_event_label = str(event.get("label", event.get("kind", "gesture")))
	if active == "none" and next_event_time >= 0.0:
		active_event_label.text = "Next drawing: %s at %.2fs" % [next_event_label, next_event_time]
	else:
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
		"audio":
			audio_user_enabled = visible
			_sync_audio_playback()
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
	var show_audio := condition != "no_audio" and audio_player != null
	var show_annotations := condition == "stage2"
	_set_layer_toggle_value("gestures", show_gestures)
	_set_layer_toggle_value("objects", show_objects)
	_set_layer_toggle_value("sand", show_sand)
	_set_layer_toggle_value("heightmap_surface", show_sand)
	_set_layer_toggle_value("audio", show_audio)
	_set_layer_toggle_value("annotations", show_annotations)
	_set_layer_visible("gestures", show_gestures)
	_set_layer_visible("objects", show_objects)
	_set_layer_visible("sand", show_sand)
	_set_layer_visible("heightmap_surface", show_sand)
	_set_layer_visible("audio", show_audio)
	_set_layer_visible("annotations", show_annotations)
	if experiment_mode:
		_apply_experiment_condition_locks()
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
		study_panel.visible = not focus_mode and not experiment_mode
	if experiment_runner != null:
		experiment_runner.visible = not focus_mode and experiment_mode
	if lower_dock_panel != null:
		lower_dock_panel.visible = not focus_mode and not experiment_mode
	if fixed_views_panel != null:
		fixed_views_panel.visible = (not focus_mode) and reference_views_visible
	_set_reference_viewports_active(
		(not focus_mode) and reference_views_visible
	)
	if focus_button != null:
		focus_button.text = "Study panels" if focus_mode else "Focus 3D"
	_log_event("focus_mode", {"enabled": focus_mode})


func _toggle_reference_views() -> void:
	reference_views_visible = not reference_views_visible
	if fixed_views_panel != null:
		fixed_views_panel.visible = reference_views_visible and not focus_mode
	_set_reference_viewports_active(
		reference_views_visible and not focus_mode
	)
	if reference_views_button != null:
		reference_views_button.text = "Hide refs" if reference_views_visible else "Reference views"
	_log_event("reference_views", {"visible": reference_views_visible})


func _set_reference_viewports_active(active: bool) -> void:
	for viewport in [top_viewport, front_viewport]:
		if viewport == null:
			continue
		viewport.render_target_update_mode = (
			SubViewport.UPDATE_ALWAYS
			if active
			else SubViewport.UPDATE_DISABLED
		)


func _set_heightmap_surface_enabled(enabled: bool) -> void:
	if sand_mesh_instance != null:
		sand_mesh_instance.visible = not enabled
	if heightmap_surface_node != null:
		heightmap_surface_node.visible = enabled
	if enabled:
		_apply_surface_texture_source()


func _on_play_pressed() -> void:
	_set_playback_state(not is_playing)


func _set_playback_state(playing: bool) -> void:
	if playing and playhead >= duration - 0.001:
		playhead = 0.0
		if time_slider != null:
			time_slider.set_value_no_signal(playhead)
		_update_scene_from_time()
	is_playing = playing
	if play_button != null:
		play_button.text = "Pause" if is_playing else "Play"
	_set_surface_stream_playing(is_playing and use_video_streams)
	_sync_audio_playback(true)
	_log_event("transport", {"playing": is_playing, "time": playhead})


func _on_time_changed(value: float) -> void:
	_seek_playhead(value)


func _seek_playhead(value: float) -> void:
	playhead = clamp(value, 0.0, duration)
	if time_slider != null:
		time_slider.set_value_no_signal(playhead)
	_update_scene_from_time()
	_sync_audio_playback(true)
	_log_event("seek", {"time": playhead})


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
	experiment_event_buffer.append(entry)
	if web_bridge_ready and event_name != "surface_frame_selected":
		_emit_web_message("event", entry)
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
	static_topdown_hand_texture = null
	static_topdown_hand_geometry_texture = null

	static_depth_texture = _load_surface_texture(depth_path)
	static_surface_texture = _load_surface_texture(texture_path)

	var mask_path := str(data_sources.get("surface_mask", ""))
	static_surface_mask_texture = _load_surface_texture(mask_path)
	var hand_overlay_path := str(
		data_sources.get("virtual_hand_overlay", "")
	)
	static_topdown_hand_texture = _load_surface_texture(hand_overlay_path)
	var hand_geometry_path := str(
		data_sources.get("virtual_hand_geometry", "")
	)
	static_topdown_hand_geometry_texture = _load_surface_texture(
		hand_geometry_path
	)

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
	_apply_topdown_hand_texture_source()


func _load_surface_texture(path: String) -> Texture2D:
	if path == "":
		return null
	if surface_texture_cache.has(path):
		return surface_texture_cache[path]
	if _is_http_path(path):
		if not surface_texture_pending.has(path):
			surface_texture_pending[path] = true
			_load_remote_surface_texture(path)
		return null
	if ResourceLoader.exists(path):
		var texture := load(path)
		if texture is Texture2D:
			surface_texture_cache[path] = texture
			return texture
	var global_path := ProjectSettings.globalize_path(path)
	var file_to_load := global_path if FileAccess.file_exists(global_path) else (path if FileAccess.file_exists(path) else "")
	if file_to_load != "":
		var img := Image.load_from_file(file_to_load)
		if img != null and not img.is_empty():
			var texture := ImageTexture.create_from_image(img)
			surface_texture_cache[path] = texture
			return texture
	return null


func _load_remote_surface_texture(path: String) -> void:
	var body := await _http_get(path)
	surface_texture_pending.erase(path)
	if body.is_empty():
		return
	var image := Image.new()
	var error := image.load_png_from_buffer(body)
	if error != OK:
		push_error("Cannot decode remote PNG: " + path)
		return
	var texture := ImageTexture.create_from_image(image)
	surface_texture_cache[path] = texture
	if surface_frame_pending_index >= 0 and _surface_frame_textures_ready(surface_frame_pending_index):
		var requested_index := surface_frame_pending_index
		surface_frame_pending_index = -1
		_set_surface_frame(requested_index)
		return
	if (
		_source_path("depth_map", SAND_HEIGHTMAP_PATH) == path
		or _source_path("texture_map", SAND_TEXTURE_PATH) == path
		or _source_path("surface_mask", "") == path
		or str(data_sources.get("virtual_hand_overlay", "")) == path
		or str(data_sources.get("virtual_hand_geometry", "")) == path
	):
		_reload_static_surface_textures()
		_apply_surface_texture_source()


func _apply_mano_hand_mesh() -> void:
	if mano_hand_surface_node == null:
		return
	var path := str(data_sources.get("virtual_hand_mesh", ""))
	if path == "":
		mano_hand_surface_node.mesh = null
		mano_hand_surface_node.visible = false
		return
	var mesh := _load_mano_mesh(path)
	if mesh == null:
		mano_hand_surface_node.visible = false
		return
	mano_hand_surface_node.mesh = mesh
	mano_hand_surface_node.visible = true


func _load_mano_mesh(path: String) -> ArrayMesh:
	if path == "":
		return null
	if mano_mesh_cache.has(path):
		return mano_mesh_cache[path]
	if _is_http_path(path):
		if not mano_mesh_pending.has(path):
			mano_mesh_pending[path] = true
			_load_remote_mano_mesh(path)
		return null
	if not FileAccess.file_exists(path):
		return null
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return null
	var mesh: ArrayMesh
	if path.ends_with(".meshbin.gz"):
		mesh = _mano_mesh_from_bytes(file.get_buffer(file.get_length()), path)
	else:
		mesh = _mano_mesh_from_payload(JSON.parse_string(file.get_as_text()), path)
	if mesh != null:
		mano_mesh_cache[path] = mesh
	return mesh


func _load_remote_mano_mesh(path: String) -> void:
	var body := await _http_get(path)
	mano_mesh_pending.erase(path)
	if body.is_empty():
		return
	var mesh: ArrayMesh
	if path.ends_with(".meshbin.gz"):
		mesh = _mano_mesh_from_bytes(body, path)
	else:
		mesh = _mano_mesh_from_payload(
			JSON.parse_string(body.get_string_from_utf8()), path
		)
	if mesh == null:
		return
	mano_mesh_cache[path] = mesh
	if (
		surface_frame_pending_index >= 0
		and _surface_frame_textures_ready(surface_frame_pending_index)
	):
		var requested_index := surface_frame_pending_index
		surface_frame_pending_index = -1
		_set_surface_frame(requested_index)
		return
	if str(data_sources.get("virtual_hand_mesh", "")) == path:
		_apply_mano_hand_mesh()


func _mano_mesh_from_bytes(body: PackedByteArray, source_path: String) -> ArrayMesh:
	var data := body
	if source_path.ends_with(".gz"):
		data = body.decompress_dynamic(
			1024 * 1024, FileAccess.COMPRESSION_GZIP
		)
	if data.size() < 20 or data.slice(0, 4).get_string_from_ascii() != "MNRB":
		push_error("Invalid MANO binary header: " + source_path)
		return null
	var version := int(data.decode_u32(4))
	var vertex_count := int(data.decode_u32(8))
	var index_count := int(data.decode_u32(12))
	if (
		version != 1
		or vertex_count <= 0
		or vertex_count > 100000
		or index_count <= 0
		or index_count % 3 != 0
	):
		push_error("Unsupported MANO binary layout: " + source_path)
		return null
	var expected_size := 20 + vertex_count * 3 * 4 * 2 + index_count * 4
	if data.size() != expected_size:
		push_error(
			"MANO binary size mismatch (%d != %d): %s"
			% [data.size(), expected_size, source_path]
		)
		return null

	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	vertices.resize(vertex_count)
	normals.resize(vertex_count)
	var offset := 20
	for index in range(vertex_count):
		var vertex := Vector3(
			data.decode_float(offset),
			data.decode_float(offset + 4),
			data.decode_float(offset + 8)
		)
		offset += 12
		if not vertex.is_finite():
			push_error("Non-finite MANO binary vertex: " + source_path)
			return null
		vertices[index] = vertex
	for index in range(vertex_count):
		var normal := Vector3(
			data.decode_float(offset),
			data.decode_float(offset + 4),
			data.decode_float(offset + 8)
		)
		offset += 12
		if not normal.is_finite():
			push_error("Non-finite MANO binary normal: " + source_path)
			return null
		normals[index] = normal.normalized()
	var indices := PackedInt32Array()
	indices.resize(index_count)
	for index in range(index_count):
		var vertex_index := int(data.decode_u32(offset))
		offset += 4
		if vertex_index < 0 or vertex_index >= vertex_count:
			push_error("Out-of-range MANO binary index: " + source_path)
			return null
		indices[index] = vertex_index
	return _mano_mesh_from_arrays(vertices, normals, indices)


func _mano_mesh_from_payload(payload, source_path: String) -> ArrayMesh:
	if typeof(payload) != TYPE_DICTIONARY:
		push_error("Invalid MANO mesh JSON: " + source_path)
		return null
	var vertex_values: Array = payload.get("vertices", [])
	var normal_values: Array = payload.get("normals", [])
	var index_values: Array = payload.get("indices", [])
	if (
		vertex_values.is_empty()
		or vertex_values.size() % 3 != 0
		or normal_values.size() != vertex_values.size()
		or index_values.is_empty()
		or index_values.size() % 3 != 0
	):
		push_error("Malformed MANO mesh arrays: " + source_path)
		return null

	var vertex_count := int(vertex_values.size() / 3)
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	vertices.resize(vertex_count)
	normals.resize(vertex_count)
	for index in range(vertex_count):
		var offset := index * 3
		var vertex := Vector3(
			float(vertex_values[offset]),
			float(vertex_values[offset + 1]),
			float(vertex_values[offset + 2])
		)
		var normal := Vector3(
			float(normal_values[offset]),
			float(normal_values[offset + 1]),
			float(normal_values[offset + 2])
		)
		if not vertex.is_finite() or not normal.is_finite():
			push_error("Non-finite MANO vertex/normal: " + source_path)
			return null
		vertices[index] = vertex
		normals[index] = normal.normalized()

	var indices := PackedInt32Array()
	indices.resize(index_values.size())
	for index in range(index_values.size()):
		var vertex_index := int(index_values[index])
		if vertex_index < 0 or vertex_index >= vertex_count:
			push_error("Out-of-range MANO triangle index: " + source_path)
			return null
		indices[index] = vertex_index
	return _mano_mesh_from_arrays(vertices, normals, indices)


func _mano_mesh_from_arrays(
	vertices: PackedVector3Array,
	normals: PackedVector3Array,
	indices: PackedInt32Array
) -> ArrayMesh:
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_INDEX] = indices
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	mesh.surface_set_name(0, "MANO_RGBD")
	return mesh


func _wait_for_initial_surface_textures(
	timeout_ms := 15000,
	generation := -1
) -> void:
	var required_paths := [
		_source_path("depth_map", SAND_HEIGHTMAP_PATH),
		_source_path("texture_map", SAND_TEXTURE_PATH),
		_source_path("surface_mask", ""),
		str(data_sources.get("virtual_hand_overlay", "")),
		str(data_sources.get("virtual_hand_geometry", ""))
	]
	var required_mesh_path := str(data_sources.get("virtual_hand_mesh", ""))
	var has_remote_path := false
	for path in required_paths:
		if _is_http_path(str(path)):
			has_remote_path = true
			break
	if _is_http_path(required_mesh_path):
		has_remote_path = true
	if not has_remote_path:
		return

	var deadline := Time.get_ticks_msec() + timeout_ms
	while Time.get_ticks_msec() < deadline:
		if generation >= 0 and generation != session_load_generation:
			return
		var ready := true
		for path in required_paths:
			var resolved := str(path)
			if resolved != "" and _is_http_path(resolved) and not surface_texture_cache.has(resolved):
				ready = false
				break
		if (
			ready
			and _is_http_path(required_mesh_path)
			and not mano_mesh_cache.has(required_mesh_path)
		):
			ready = false
		if ready:
			return
		await get_tree().process_frame
	push_warning("Timed out waiting for initial remote surface textures")


func _wait_for_surface_buffer(
	minimum_frame_count := SURFACE_AUTOPLAY_BUFFER_FRAMES,
	timeout_ms := 15000,
	generation := -1
) -> void:
	if processed_surface_frames.is_empty() or surface_frame_index < 0:
		return
	var has_remote_path := false
	for path in _surface_frame_texture_paths(surface_frame_index):
		if _is_http_path(path):
			has_remote_path = true
			break
	if not has_remote_path:
		return
	_prefetch_surface_window(surface_frame_index)
	var end: int = min(
		processed_surface_frames.size(),
		surface_frame_index + max(1, minimum_frame_count)
	)
	var deadline := Time.get_ticks_msec() + timeout_ms
	while Time.get_ticks_msec() < deadline:
		if generation >= 0 and generation != session_load_generation:
			return
		var ready := true
		for index in range(surface_frame_index, end):
			if not _surface_frame_textures_ready(index):
				ready = false
				break
		if ready:
			return
		await get_tree().process_frame
	push_warning("Timed out waiting for remote surface playback buffer")


func _heightmap_material() -> Material:
	if not ResourceLoader.exists(SAND_DEPTH_SHADER_PATH):
		return null
	var depth_path := _source_path("depth_map", SAND_HEIGHTMAP_PATH)
	var texture_path := _source_path("texture_map", SAND_TEXTURE_PATH)
	var uses_remote_surface := _is_http_path(depth_path) or _is_http_path(texture_path)
	var depth_exists := uses_remote_surface or ResourceLoader.exists(depth_path) or FileAccess.file_exists(depth_path) or FileAccess.file_exists(ProjectSettings.globalize_path(depth_path))
	var texture_exists := uses_remote_surface or ResourceLoader.exists(texture_path) or FileAccess.file_exists(texture_path) or FileAccess.file_exists(ProjectSettings.globalize_path(texture_path))
	if not depth_exists or not texture_exists:
		return null

	var shader := load(SAND_DEPTH_SHADER_PATH)
	if not shader is Shader:
		return null

	var material := ShaderMaterial.new()
	material.shader = shader
	heightmap_material = material
	_reload_static_surface_textures()
	if static_depth_texture == null:
		static_depth_texture = _load_surface_texture(depth_path)
	if static_surface_texture == null:
		static_surface_texture = _load_surface_texture(texture_path)
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
	material.set_shader_parameter("baseline_height_offset", surface_baseline_height_offset)
	material.set_shader_parameter("material_strength", 0.0)
	return material


func _topdown_hand_overlay_material() -> Material:
	var shader_path := TOPDOWN_HAND_OVERLAY_SHADER_PATH
	if str(data_sources.get("virtual_hand_geometry", "")) != "":
		shader_path = (
			TOPDOWN_HAND_RGBD_SHELL_SHADER_PATH
			if bool(data_sources.get("virtual_hand_measured_shell_v2", false))
			else TOPDOWN_HAND_RGBD_SHADER_PATH
		)
	if not ResourceLoader.exists(shader_path):
		return null
	var shader := load(shader_path)
	if not shader is Shader:
		return null
	var material := ShaderMaterial.new()
	material.shader = shader
	if static_depth_texture != null:
		material.set_shader_parameter("depth_map", static_depth_texture)
	if static_topdown_hand_texture != null:
		material.set_shader_parameter(
			"hand_overlay",
			static_topdown_hand_texture
		)
	if static_topdown_hand_geometry_texture != null:
		material.set_shader_parameter(
			"hand_geometry",
			static_topdown_hand_geometry_texture
		)
	material.set_shader_parameter(
		"hand_max_lift_meters",
		float(data_sources.get("virtual_hand_max_lift_meters", 0.36))
	)
	material.set_shader_parameter(
		"hand_world_units_per_meter",
		float(
			data_sources.get(
				"virtual_hand_world_units_per_meter",
				3.0
			)
		)
	)
	if bool(data_sources.get("virtual_hand_measured_shell_v2", false)):
		material.set_shader_parameter(
			"shell_color",
			_array_to_vec3(
				data_sources.get(
					"virtual_hand_shell_color_rgb",
					[0.7215686, 0.4313725, 0.3411765]
				)
			)
		)
		material.set_shader_parameter(
			"shell_texture_strength",
			float(data_sources.get("virtual_hand_shell_texture_strength", 0.58))
		)
		material.set_shader_parameter(
			"shell_edge_extension_texels",
			float(data_sources.get("virtual_hand_shell_edge_extension_texels", 2.0))
		)
		material.set_shader_parameter(
			"shell_normal_radius_texels",
			float(data_sources.get("virtual_hand_shell_normal_radius_texels", 2.0))
		)
	var depth_path := _source_path("depth_map", SAND_HEIGHTMAP_PATH)
	if depth_path.get_file().begins_with("detail_depth_fused_"):
		material.set_shader_parameter("arg_1", 3.4)
		material.set_shader_parameter("background", 0.5)
		material.set_shader_parameter("eps_0", 0.012)
		material.set_shader_parameter("eps_1", 0.11)
	elif depth_path.get_file().begins_with("detail_depth_"):
		material.set_shader_parameter("arg_1", 3.0)
		material.set_shader_parameter("background", 0.5)
		material.set_shader_parameter("eps_0", 0.004)
		material.set_shader_parameter("eps_1", 0.08)
	else:
		material.set_shader_parameter("arg_1", 11.625)
		material.set_shader_parameter("background", 1.0)
		material.set_shader_parameter("eps_0", 0.08)
		material.set_shader_parameter("eps_1", 0.415)
	var calibration: Dictionary = data_sources.get("calibration", {})
	material.set_shader_parameter(
		"depth_uv_scale",
		_array_to_vec2(calibration.get("depth_uv_scale", [1.0, 1.0]))
	)
	material.set_shader_parameter(
		"texture_uv_scale",
		_array_to_vec2(calibration.get("texture_uv_scale", [1.0, 1.0]))
	)
	material.set_shader_parameter(
		"depth_uv_offset",
		Vector2(
			float(surface_controls["depth_u"]),
			float(surface_controls["depth_v"])
		)
	)
	material.set_shader_parameter(
		"texture_uv_offset",
		Vector2(
			float(surface_controls["texture_u"]),
			float(surface_controls["texture_v"])
		)
	)
	material.set_shader_parameter(
		"displacement_scale",
		float(surface_controls["displacement"])
	)
	material.set_shader_parameter(
		"baseline_height_offset",
		surface_baseline_height_offset
	)
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
	heightmap_material.set_shader_parameter("detail_scale_m", float(calibration.get("detail_scale_m", 0.004)))
	heightmap_material.set_shader_parameter("neutral_gray", float(calibration.get("neutral_gray", 128.0)))
	heightmap_material.set_shader_parameter("cavity_strength", float(calibration.get("cavity_strength", 0.35)))
	heightmap_material.set_shader_parameter("cavity_clamp", float(calibration.get("cavity_clamp", 0.50)))
	heightmap_material.set_shader_parameter("noise_threshold_m", float(calibration.get("noise_threshold_m", 0.0005)))
	heightmap_material.set_shader_parameter("use_rgb_grooves", bool(calibration.get("use_rgb_grooves", false)))
	heightmap_material.set_shader_parameter("rgb_groove_strength", float(calibration.get("rgb_groove_strength", 0.0)))
	heightmap_material.set_shader_parameter(
		"depth_uv_scale",
		_array_to_vec2(calibration.get("depth_uv_scale", [1.0, 1.0]))
	)
	heightmap_material.set_shader_parameter(
		"texture_uv_scale",
		_array_to_vec2(calibration.get("texture_uv_scale", [1.0, 1.0]))
	)
	if topdown_hand_material != null:
		topdown_hand_material.set_shader_parameter(
			"depth_uv_offset",
			Vector2(
				float(surface_controls["depth_u"]),
				float(surface_controls["depth_v"])
			)
		)
		topdown_hand_material.set_shader_parameter(
			"texture_uv_offset",
			Vector2(
				float(surface_controls["texture_u"]),
				float(surface_controls["texture_v"])
			)
		)
		topdown_hand_material.set_shader_parameter(
			"depth_uv_scale",
			_array_to_vec2(
				calibration.get("depth_uv_scale", [1.0, 1.0])
			)
		)
		topdown_hand_material.set_shader_parameter(
			"texture_uv_scale",
			_array_to_vec2(
				calibration.get("texture_uv_scale", [1.0, 1.0])
			)
		)
		topdown_hand_material.set_shader_parameter(
			"displacement_scale",
			float(surface_controls["displacement"])
		)


func _set_surface_stream_playing(playing: bool) -> void:
	for player in [depth_video_player, texture_video_player]:
		if player == null:
			continue
		if playing:
			if not player.is_playing():
				player.play()
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
