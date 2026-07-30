extends PanelContainer

signal condition_requested(condition: String)
signal phase_changed(phase: String)
signal evidence_requested(question_id: String)
signal submission_ready(payload: Dictionary)
signal event_emitted(event_name: String, payload: Dictionary)

const STAGE1_CONDITIONS := [
	"baseline",
	"no_audio",
	"no_gestures",
	"no_objects",
	"no_sand",
]

var protocol: Dictionary = {}
var session_payload: Dictionary = {}
var launch_config: Dictionary = {}
var readiness: Dictionary = {}
var experiment_content: Dictionary = {}
var stage := "pilot"
var condition := "baseline"
var run_id := ""
var phase := "idle"
var phase_started_ms := 0
var phase_timings := {}
var profile := {}
var responses := {}
var questionnaire := {}
var evidence_snapshots := {}
var question_controls := {}
var export_status := ""

var content_root: VBoxContainer
var phase_label: Label
var progress_label: Label
var validation_label: Label


func _ready() -> void:
	_ensure_ui()


func configure(
	protocol_data: Dictionary,
	session_data: Dictionary,
	config: Dictionary,
	readiness_data: Dictionary
) -> void:
	_ensure_ui()
	protocol = protocol_data
	session_payload = session_data
	launch_config = config
	readiness = readiness_data
	experiment_content = session_payload.get("experiment", {})
	stage = str(launch_config.get("stage", "pilot"))
	if stage not in ["stage1", "stage2", "pilot"]:
		stage = "pilot"
	run_id = _make_run_id()
	profile.clear()
	responses.clear()
	questionnaire.clear()
	evidence_snapshots.clear()
	phase_timings.clear()
	_transition_to("consent")
	_emit_event("experiment_configured", {
		"run_id": run_id,
		"stage": stage,
		"session_id": session_payload.get("id", ""),
		"readiness": readiness,
	})


func accept_evidence_snapshot(question_id: String, snapshot: Dictionary) -> void:
	evidence_snapshots[question_id] = snapshot
	if question_controls.has(question_id):
		var controls: Dictionary = question_controls[question_id]
		var label: Label = controls.get("evidence_label")
		if label != null:
			label.text = "Marked at %.2fs" % float(snapshot.get("playhead", 0.0))
	_emit_event("task_evidence_attached", {
		"question_id": question_id,
		"snapshot": snapshot,
	})


func set_export_status(message: String) -> void:
	export_status = message
	if phase == "complete":
		_render_phase()


func _ensure_ui() -> void:
	if content_root != null:
		return
	name = "ExperimentRunner"
	add_theme_stylebox_override("panel", _panel_style(Color(0.035, 0.044, 0.041, 0.98), 14))

	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(scroll)

	content_root = VBoxContainer.new()
	content_root.name = "ExperimentContent"
	content_root.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	content_root.add_theme_constant_override("separation", 10)
	scroll.add_child(content_root)


func _transition_to(next_phase: String) -> void:
	var now := Time.get_ticks_msec()
	if phase != "idle" and phase_started_ms > 0:
		phase_timings[phase] = int(phase_timings.get(phase, 0)) + now - phase_started_ms
	phase = next_phase
	phase_started_ms = now
	_render_phase()
	phase_changed.emit(phase)
	_emit_event("experiment_phase", {"phase": phase})


func _render_phase() -> void:
	_clear_content()
	_add_header()
	match phase:
		"consent":
			_render_consent()
		"profile":
			_render_profile()
		"training":
			_render_training()
		"task":
			_render_task()
		"questionnaire":
			_render_questionnaire()
		"complete":
			_render_complete()


func _clear_content() -> void:
	question_controls.clear()
	for child in content_root.get_children():
		content_root.remove_child(child)
		child.queue_free()


func _add_header() -> void:
	var title := Label.new()
	title.text = "Sand Stories Study"
	title.add_theme_font_size_override("font_size", 22)
	title.add_theme_color_override("font_color", Color("#f0ead6"))
	content_root.add_child(title)

	phase_label = Label.new()
	phase_label.text = _phase_title()
	phase_label.add_theme_font_size_override("font_size", 16)
	phase_label.add_theme_color_override("font_color", Color("#82b8ae"))
	content_root.add_child(phase_label)

	progress_label = Label.new()
	progress_label.text = "Run %s  |  %s" % [run_id, stage.to_upper()]
	progress_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	progress_label.add_theme_color_override("font_color", Color("#b8c5bf"))
	content_root.add_child(progress_label)

	validation_label = Label.new()
	validation_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	validation_label.add_theme_color_override("font_color", Color("#f2a65e"))
	content_root.add_child(validation_label)


func _render_consent() -> void:
	_add_wrapped_label(
		"This study investigates how sand, gesture, narration, objects, and "
		+ "cross-modal annotations affect interpretation. Participation is "
		+ "voluntary. Do not enter names or other identifying information."
	)
	if stage == "pilot":
		_add_notice(
			"Pilot mode: this run is for interface validation only and must not "
			+ "be treated as research data."
		)
	var warnings: Array = readiness.get("warnings", [])
	if not warnings.is_empty():
		_add_notice("Session readiness:\n- " + "\n- ".join(PackedStringArray(warnings)))

	var consent := CheckBox.new()
	consent.text = "I have read the study information and consent to continue."
	_style_check(consent)
	content_root.add_child(consent)

	var continue_button := _make_button("Continue", true)
	continue_button.disabled = true
	consent.toggled.connect(func(value: bool) -> void:
		continue_button.disabled = not value
	)
	continue_button.pressed.connect(func() -> void:
		_emit_event("consent_recorded", {"consented": true})
		_transition_to("profile")
	)
	content_root.add_child(continue_button)


func _render_profile() -> void:
	_add_wrapped_label(
		"Enter an anonymous participant code and the covariates specified in "
		+ "the proposal. These values are stored with this run."
	)

	var participant_input := LineEdit.new()
	participant_input.placeholder_text = "Anonymous participant code"
	participant_input.text = str(launch_config.get("participant", ""))
	_style_line_edit(participant_input)
	content_root.add_child(participant_input)

	var age_option := _add_option(
		"Age range",
		["Prefer not to say", "18-24", "25-34", "35-44", "45-54", "55+"]
	)
	var sand_option := _add_option(
		"Sand-drawing experience",
		["None", "Seen it before", "Occasional", "Regular practitioner", "Expert"]
	)
	var analysis_option := _add_option(
		"Multimodal-analysis experience",
		["None", "Some familiarity", "Regular use", "Professional/research expert"]
	)
	var group_option: OptionButton
	if stage == "stage2":
		group_option = _add_option(
			"Stage 2 participant group",
			["Non-expert", "Practitioner", "Expert"]
		)

	var continue_button := _make_button("Continue to training", true)
	continue_button.pressed.connect(
		_on_profile_continue.bind(
			participant_input,
			age_option,
			sand_option,
			analysis_option,
			group_option
		)
	)
	content_root.add_child(continue_button)


func _on_profile_continue(
	participant_input: LineEdit,
	age_option: OptionButton,
	sand_option: OptionButton,
	analysis_option: OptionButton,
	group_option: OptionButton
) -> void:
	var participant_code := participant_input.text.strip_edges()
	if participant_code == "":
		validation_label.text = "An anonymous participant code is required."
		return
	profile = {
		"participantCode": participant_code,
		"ageRange": _selected_text(age_option),
		"sandDrawingExperience": _selected_text(sand_option),
		"multimodalAnalysisExperience": _selected_text(analysis_option),
	}
	if group_option != null:
		profile["stage2Group"] = _selected_text(group_option)
	condition = _assigned_condition(participant_code)
	_emit_event("participant_profile", profile)
	_transition_to("training")


func _render_training() -> void:
	var training_condition := "stage2" if stage == "stage2" else "baseline"
	condition_requested.emit(training_condition)
	_add_wrapped_label(
		"Training uses the complete representation. Try each interaction, then "
		+ "confirm it below. The main Stage 1 condition is revealed only after "
		+ "training."
	)
	var checks: Array[CheckBox] = []
	var training_items: Array = protocol.get("trainingTasks", [
		"Orbit, pan, and zoom the 3D scene.",
		"Play, pause, and seek on the timeline.",
		"Toggle at least one available modality layer.",
	])
	if stage == "stage2":
		training_items = protocol.get("stage2TrainingTasks", training_items)
	for item in training_items:
		var check := CheckBox.new()
		check.text = str(item)
		check.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		_style_check(check)
		content_root.add_child(check)
		checks.append(check)

	var begin_button := _make_button("Begin main task", true)
	begin_button.disabled = true
	for check in checks:
		check.toggled.connect(_on_training_check_toggled.bind(begin_button, checks))
	begin_button.pressed.connect(func() -> void:
		condition_requested.emit(condition)
		_emit_event("condition_assigned", {
			"condition": condition,
			"assignmentMethod": (
				"fixed"
				if str(launch_config.get("condition", "")) != ""
				else "deterministic_random"
			),
		})
		_transition_to("task")
	)
	content_root.add_child(begin_button)


func _on_training_check_toggled(
	_value: bool,
	begin_button: Button,
	checks: Array[CheckBox]
) -> void:
	for check in checks:
		if not check.button_pressed:
			begin_button.disabled = true
			return
	begin_button.disabled = false


func _render_task() -> void:
	_add_notice(_condition_description(condition))
	var summary_prompt := str(
		experiment_content.get(
			"summaryPrompt",
			"Summarise the content or spatial knowledge communicated by this session."
		)
	)
	_add_wrapped_label(summary_prompt)
	var summary := TextEdit.new()
	summary.name = "SummaryResponse"
	summary.placeholder_text = "Participant summary"
	summary.custom_minimum_size = Vector2(0, 120)
	_style_text_edit(summary)
	content_root.add_child(summary)

	var questions := _task_questions()
	if questions.is_empty():
		_add_notice(
			"No session-specific questions are configured. This session cannot "
			+ "be used for data collection."
		)
	for index in range(questions.size()):
		var question: Dictionary = questions[index]
		_add_question(index, question)

	var submit_button := _make_button("Submit task responses", true)
	submit_button.disabled = questions.is_empty() and stage != "pilot"
	submit_button.pressed.connect(_on_task_submit.bind(summary, questions))
	content_root.add_child(submit_button)


func _add_question(index: int, question: Dictionary) -> void:
	var question_id := str(question.get("id", "question_%d" % (index + 1)))
	var prompt := Label.new()
	prompt.text = "%d. %s" % [index + 1, str(question.get("prompt", ""))]
	prompt.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	prompt.add_theme_font_size_override("font_size", 15)
	prompt.add_theme_color_override("font_color", Color("#e7e4d6"))
	content_root.add_child(prompt)

	var answer_control: Control
	var question_type := str(question.get("type", "choice"))
	if question_type == "choice":
		var options := OptionButton.new()
		options.add_item("Select an answer")
		for option in question.get("options", []):
			options.add_item(str(option))
		_style_button(options)
		content_root.add_child(options)
		answer_control = options
	else:
		var answer := TextEdit.new()
		answer.placeholder_text = "Short answer"
		answer.custom_minimum_size = Vector2(0, 90)
		_style_text_edit(answer)
		content_root.add_child(answer)
		answer_control = answer

	var evidence := TextEdit.new()
	evidence.placeholder_text = str(
		question.get(
			"evidencePrompt",
			"Explain what evidence in the representation supports this answer."
		)
	)
	evidence.custom_minimum_size = Vector2(0, 80)
	_style_text_edit(evidence)
	content_root.add_child(evidence)

	var evidence_row := HBoxContainer.new()
	var mark_button := _make_button("Mark current 3D view", false)
	mark_button.pressed.connect(_on_evidence_button_pressed.bind(question_id))
	evidence_row.add_child(mark_button)
	var evidence_label := Label.new()
	evidence_label.text = "No timestamp marked"
	evidence_label.add_theme_color_override("font_color", Color("#aebbb5"))
	evidence_row.add_child(evidence_label)
	content_root.add_child(evidence_row)

	question_controls[question_id] = {
		"type": question_type,
		"answer": answer_control,
		"evidence": evidence,
		"evidence_label": evidence_label,
		"prompt": question.get("prompt", ""),
	}


func _on_evidence_button_pressed(question_id: String) -> void:
	evidence_requested.emit(question_id)


func _on_task_submit(summary: TextEdit, questions: Array) -> void:
	var summary_text := summary.text.strip_edges()
	if summary_text == "":
		validation_label.text = "Please complete the session summary."
		return
	var task_answers := []
	for index in range(questions.size()):
		var question: Dictionary = questions[index]
		var question_id := str(question.get("id", "question_%d" % (index + 1)))
		var controls: Dictionary = question_controls.get(question_id, {})
		var answer := ""
		if str(controls.get("type", "")) == "choice":
			var option: OptionButton = controls.get("answer")
			if option == null or option.selected <= 0:
				validation_label.text = "Please answer question %d." % (index + 1)
				return
			answer = option.get_item_text(option.selected)
		else:
			var short_answer: TextEdit = controls.get("answer")
			answer = "" if short_answer == null else short_answer.text.strip_edges()
			if answer == "":
				validation_label.text = "Please answer question %d." % (index + 1)
				return
		var evidence: TextEdit = controls.get("evidence")
		var evidence_text := "" if evidence == null else evidence.text.strip_edges()
		if evidence_text == "":
			validation_label.text = "Please provide evidence for question %d." % (index + 1)
			return
		task_answers.append({
			"id": question_id,
			"prompt": controls.get("prompt", ""),
			"answer": answer,
			"evidence": evidence_text,
			"viewSnapshot": evidence_snapshots.get(question_id, {}),
		})
	responses = {
		"summary": summary_text,
		"questions": task_answers,
	}
	_emit_event("task_submitted", {
		"questionCount": task_answers.size(),
		"hasSummary": true,
	})
	_transition_to("questionnaire")


func _render_questionnaire() -> void:
	_add_wrapped_label(
		"Rate your experience. NASA-TLX items use 0 (very low) to 100 "
		+ "(very high); performance uses 0 (perfect) to 100 (failure)."
	)
	var ease := _add_likert("The interface was easy to use.")
	var confidence := _add_likert("I am confident in my interpretation.")
	var difficulty := _add_likert("The interpretation tasks were difficult.")

	var reliance := {}
	_add_wrapped_label("Which modalities did you rely on?")
	for key in ["sand", "gestures", "audio", "objects", "annotations"]:
		var check := CheckBox.new()
		check.text = key.capitalize()
		_style_check(check)
		content_root.add_child(check)
		reliance[key] = check

	var nasa_controls := {}
	for dimension in [
		"mentalDemand",
		"physicalDemand",
		"temporalDemand",
		"performance",
		"effort",
		"frustration",
	]:
		nasa_controls[dimension] = _add_nasa_slider(dimension)

	var annotation_usefulness: OptionButton
	var observer_notes: TextEdit
	if stage == "stage2":
		annotation_usefulness = _add_likert(
			"The explicit annotations and referential links were useful."
		)
		observer_notes = TextEdit.new()
		observer_notes.placeholder_text = (
			"Observer/interview notes: uncertainties, information-seeking "
			+ "strategies, and think-aloud observations"
		)
		observer_notes.custom_minimum_size = Vector2(0, 120)
		_style_text_edit(observer_notes)
		content_root.add_child(observer_notes)

	var submit_button := _make_button("Finish and export", true)
	submit_button.pressed.connect(
		_on_questionnaire_submit.bind(
			ease,
			confidence,
			difficulty,
			reliance,
			nasa_controls,
			annotation_usefulness,
			observer_notes
		)
	)
	content_root.add_child(submit_button)


func _on_questionnaire_submit(
	ease: OptionButton,
	confidence: OptionButton,
	difficulty: OptionButton,
	reliance: Dictionary,
	nasa_controls: Dictionary,
	annotation_usefulness: OptionButton,
	observer_notes: TextEdit
) -> void:
	var relied_on := []
	for key in reliance.keys():
		var check: CheckBox = reliance[key]
		if check.button_pressed:
			relied_on.append(key)
	var nasa := {}
	for key in nasa_controls.keys():
		var slider: HSlider = nasa_controls[key]
		nasa[key] = slider.value
	questionnaire = {
		"easeOfUseLikert": ease.selected + 1,
		"interpretationConfidenceLikert": confidence.selected + 1,
		"taskDifficultyLikert": difficulty.selected + 1,
		"modalitiesReliedOn": relied_on,
		"nasaTlxRaw": nasa,
	}
	if annotation_usefulness != null:
		questionnaire["annotationUsefulnessLikert"] = (
			annotation_usefulness.selected + 1
		)
	if observer_notes != null:
		questionnaire["observerInterviewNotes"] = observer_notes.text.strip_edges()
	_transition_to("complete")
	submission_ready.emit(_submission_payload())


func _render_complete() -> void:
	_add_wrapped_label(
		"Thank you. The anonymous response package includes task responses, "
		+ "questionnaire ratings, condition assignment, phase timing, and "
		+ "interaction events recorded by the Godot runtime."
	)
	if export_status != "":
		_add_notice(export_status)
	var download_button := _make_button("Export response package again", true)
	download_button.pressed.connect(func() -> void:
		submission_ready.emit(_submission_payload())
	)
	content_root.add_child(download_button)


func _submission_payload() -> Dictionary:
	var timings := phase_timings.duplicate()
	if phase_started_ms > 0:
		timings[phase] = (
			int(timings.get(phase, 0))
			+ Time.get_ticks_msec()
			- phase_started_ms
		)
	return {
		"schemaVersion": 1,
		"protocolId": protocol.get("id", "sandstories_proposal_v1"),
		"runId": run_id,
		"stage": stage,
		"condition": condition,
		"sessionId": session_payload.get("id", ""),
		"sessionTitle": session_payload.get("title", ""),
		"readyForDataCollection": readiness.get("ready", false),
		"readinessWarnings": readiness.get("warnings", []),
		"participantProfile": profile,
		"responses": responses,
		"questionnaire": questionnaire,
		"phaseDurationsMs": timings,
		"completedUnixTime": Time.get_unix_time_from_system(),
	}


func _task_questions() -> Array:
	var key := "stage2Questions" if stage == "stage2" else "stage1Questions"
	var questions: Array = experiment_content.get(key, [])
	if not questions.is_empty():
		return questions
	var fallback := []
	for task in session_payload.get("study_tasks", []):
		if typeof(task) != TYPE_DICTIONARY:
			continue
		fallback.append({
			"id": task.get("id", "task_%d" % (fallback.size() + 1)),
			"type": "short",
			"prompt": task.get("prompt", ""),
			"evidencePrompt": "Describe the evidence used for this response.",
		})
	return fallback


func _assigned_condition(participant_code: String) -> String:
	if stage == "stage2":
		return "stage2"
	var fixed := str(launch_config.get("condition", ""))
	if fixed in STAGE1_CONDITIONS:
		return fixed
	if stage == "pilot":
		return "baseline"
	var seed_text := participant_code + ":" + str(protocol.get("id", "study"))
	var index := int((seed_text.hash() & 0x7fffffff) % STAGE1_CONDITIONS.size())
	return STAGE1_CONDITIONS[index]


func _phase_title() -> String:
	match phase:
		"consent":
			return "1 / 6  Study information and consent"
		"profile":
			return "2 / 6  Background questionnaire"
		"training":
			return "3 / 6  Interface training"
		"task":
			return "4 / 6  Interpretation task"
		"questionnaire":
			return "5 / 6  Experience and workload"
		"complete":
			return "6 / 6  Complete"
	return phase


func _condition_description(value: String) -> String:
	match value:
		"baseline":
			return "Baseline: all available modalities are present."
		"no_audio":
			return "Condition A: narration audio is intentionally omitted."
		"no_gestures":
			return "Condition B: virtual hand and gesture information is intentionally omitted."
		"no_objects":
			return "Condition C: external objects are intentionally omitted."
		"no_sand":
			return "Condition D: the reconstructed sand surface is intentionally omitted."
		"stage2":
			return "Stage 2: all modalities plus explicit annotations and referential links."
	return value


func _make_run_id() -> String:
	return "ss-%d-%06d" % [
		int(Time.get_unix_time_from_system()),
		int(randi() % 1000000),
	]


func _emit_event(event_name: String, payload: Dictionary) -> void:
	event_emitted.emit(event_name, payload)


func _add_option(label_text: String, values: Array) -> OptionButton:
	_add_wrapped_label(label_text)
	var option := OptionButton.new()
	for value in values:
		option.add_item(str(value))
	_style_button(option)
	content_root.add_child(option)
	return option


func _add_likert(label_text: String) -> OptionButton:
	_add_wrapped_label(label_text)
	var option := OptionButton.new()
	for value in range(1, 8):
		option.add_item("%d" % value)
	option.selected = 3
	_style_button(option)
	content_root.add_child(option)
	return option


func _add_nasa_slider(dimension: String) -> HSlider:
	var row := HBoxContainer.new()
	var label := Label.new()
	label.text = dimension.capitalize() + ": 50"
	label.custom_minimum_size = Vector2(155, 0)
	label.add_theme_color_override("font_color", Color("#d6ddd8"))
	row.add_child(label)
	var slider := HSlider.new()
	slider.min_value = 0
	slider.max_value = 100
	slider.step = 5
	slider.value = 50
	slider.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	slider.value_changed.connect(_on_nasa_value_changed.bind(label, dimension))
	row.add_child(slider)
	content_root.add_child(row)
	return slider


func _on_nasa_value_changed(
	value: float,
	label: Label,
	dimension: String
) -> void:
	label.text = "%s: %d" % [dimension.capitalize(), int(value)]


func _selected_text(option: OptionButton) -> String:
	if option == null or option.selected < 0:
		return ""
	return option.get_item_text(option.selected)


func _add_wrapped_label(text: String) -> Label:
	var label := Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_color_override("font_color", Color("#d6ddd8"))
	content_root.add_child(label)
	return label


func _add_notice(text: String) -> Label:
	var label := _add_wrapped_label(text)
	label.add_theme_color_override("font_color", Color("#f2c078"))
	return label


func _make_button(text: String, primary: bool) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(0, 38)
	button.add_theme_color_override("font_color", Color("#f5f1df"))
	button.add_theme_stylebox_override(
		"normal",
		_panel_style(
			Color("#176f8a") if primary else Color("#314b48"),
			8
		)
	)
	button.add_theme_stylebox_override(
		"hover",
		_panel_style(
			Color("#2184a1") if primary else Color("#3d5d59"),
			8
		)
	)
	return button


func _style_button(button: BaseButton) -> void:
	button.custom_minimum_size = Vector2(0, 34)
	button.add_theme_color_override("font_color", Color("#e8eadf"))


func _style_check(check: CheckBox) -> void:
	check.add_theme_color_override("font_color", Color("#d6ddd8"))


func _style_line_edit(edit: LineEdit) -> void:
	edit.custom_minimum_size = Vector2(0, 36)
	edit.add_theme_color_override("font_color", Color("#f0f1e8"))
	edit.add_theme_stylebox_override(
		"normal",
		_panel_style(Color("#1c2826"), 8)
	)


func _style_text_edit(edit: TextEdit) -> void:
	edit.add_theme_color_override("font_color", Color("#f0f1e8"))
	edit.add_theme_color_override("font_placeholder_color", Color("#899b94"))
	edit.add_theme_stylebox_override(
		"normal",
		_panel_style(Color("#1c2826"), 8)
	)


func _panel_style(color: Color, radius: int) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.corner_radius_top_left = radius
	style.corner_radius_top_right = radius
	style.corner_radius_bottom_left = radius
	style.corner_radius_bottom_right = radius
	style.content_margin_left = 12
	style.content_margin_right = 12
	style.content_margin_top = 10
	style.content_margin_bottom = 10
	return style
