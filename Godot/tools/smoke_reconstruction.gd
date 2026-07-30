extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var scene := load("res://scenes/Main.tscn") as PackedScene
	var main := scene.instantiate()
	root.add_child(main)
	await process_frame
	await process_frame
	await process_frame
	if main.heightmap_surface_node == null:
		push_error("Reconstruction surface was not created")
		quit(1)
		return

	main._apply_condition("no_sand")
	if main.sand_layer.visible:
		push_error("No-sand condition did not hide the sand layer")
		quit(1)
		return
	main._apply_condition("no_gestures")
	if main.gesture_layer.visible:
		push_error("No-gesture condition did not hide gestures")
		quit(1)
		return
	main._apply_condition("baseline")
	if not main.sand_layer.visible or not main.gesture_layer.visible:
		push_error("Baseline condition did not restore visible modalities")
		quit(1)
		return

	await main._load_session("res://data/best_reconstruction/session.json")
	if not str(main.data_sources.get("depth_map", "")).ends_with(
		"hybrid_depth_000171.png"
	):
		push_error("Best reconstruction session did not load")
		quit(1)
		return
	if main.depth_video_player != null or main.texture_video_player != null:
		push_error("Static session retained hidden fallback video players")
		quit(1)
		return
	print("Reconstruction scene smoke test passed")
	quit()
