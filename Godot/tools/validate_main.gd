extends SceneTree


func _initialize() -> void:
	var script := load("res://scripts/main.gd")
	var shader := load("res://assets/shaders/sand_depth.gdshader")
	var rgbd_hand_shader := load(
		"res://assets/shaders/topdown_hand_rgbd.gdshader"
	)
	var rgbd_hand_shell_shader := load(
		"res://assets/shaders/topdown_hand_rgbd_shell.gdshader"
	)
	var mano_hand_beauty_shader := load(
		"res://assets/shaders/mano_hand_beauty.gdshader"
	)
	var experiment_runner := load("res://scripts/experiment_runner.gd")
	var experiment_protocol_file := FileAccess.open(
		"res://data/experiment_protocol.json",
		FileAccess.READ
	)
	var experiment_protocol = (
		null
		if experiment_protocol_file == null
		else JSON.parse_string(experiment_protocol_file.get_as_text())
	)
	var scene := load("res://scenes/Main.tscn")
	if (
		script == null
		or shader == null
		or rgbd_hand_shader == null
		or rgbd_hand_shell_shader == null
		or mano_hand_beauty_shader == null
		or experiment_runner == null
		or typeof(experiment_protocol) != TYPE_DICTIONARY
		or scene == null
	):
		push_error("Main reconstruction resources failed to load")
		quit(1)
		return
	print("Main reconstruction resources loaded")
	quit()
