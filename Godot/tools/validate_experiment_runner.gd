extends SceneTree


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var packed := load("res://scenes/Main.tscn") as PackedScene
	if packed == null:
		_fail("Cannot load Main.tscn")
		return
	var main := packed.instantiate()
	root.add_child(main)
	for _index in range(8):
		await process_frame

	if not main.experiment_mode or main.experiment_stage != "stage1":
		_fail("Stage 1 experiment mode did not start")
		return
	if main.experiment_runner == null or not main.experiment_runner.visible:
		_fail("Experiment runner is not visible")
		return
	if main.study_panel.visible or main.condition_option.visible:
		_fail("Researcher controls remain visible in participant mode")
		return
	if not main.layer_toggles["annotations"].disabled:
		_fail("Stage 1 annotations are not locked")
		return
	if main.audio_player != null or not main.layer_toggles["audio"].disabled:
		_fail("Missing narration audio is not represented honestly")
		return
	for player in [main.depth_video_player, main.texture_video_player]:
		if player != null and player.is_playing():
			_fail("Static mode started a hidden video decoder")
			return

	var assignment_a: String = main.experiment_runner._assigned_condition("qa001")
	var assignment_b: String = main.experiment_runner._assigned_condition("qa001")
	if assignment_a != assignment_b:
		_fail("Condition assignment is not deterministic")
		return

	var condition_expectations := {
		"no_audio": ["audio"],
		"no_gestures": ["gestures"],
		"no_objects": ["objects"],
		"no_sand": ["sand", "heightmap_surface"],
	}
	for condition in condition_expectations:
		main._on_experiment_condition_requested(condition)
		for layer in condition_expectations[condition]:
			var state: Dictionary = main._web_state_snapshot()
			if bool(state.get("layers", {}).get(layer, true)):
				_fail("%s did not hide %s" % [condition, layer])
				return
			if not main.layer_toggles[layer].disabled:
				_fail("%s did not lock %s" % [condition, layer])
				return
	main._on_experiment_condition_requested("baseline")
	for layer in ["gestures", "objects", "sand", "heightmap_surface"]:
		var baseline_state: Dictionary = main._web_state_snapshot()
		if not bool(baseline_state.get("layers", {}).get(layer, false)):
			_fail("Baseline condition did not restore %s" % layer)
			return
		if main.layer_toggles[layer].disabled:
			_fail("Baseline condition left %s locked" % layer)
			return

	var readiness: Dictionary = main._experiment_readiness()
	if bool(readiness.get("ready", true)):
		_fail("Incomplete sample session was marked data-collection ready")
		return
	if not readiness.get("modalities", {}).get("annotations", false):
		_fail("Sample Stage 2 annotation data was not detected")
		return

	print(
		"Experiment runner validated: stage=%s assignment=%s warnings=%d"
		% [
			main.experiment_stage,
			assignment_a,
			readiness.get("warnings", []).size(),
		]
	)
	quit()


func _fail(message: String) -> void:
	push_error(message)
	quit(1)
