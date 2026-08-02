(function bootstrapExperimentHost() {
	"use strict";

	if (window.location.protocol === "file:") {
		const target = new URL("http://localhost:8845/experiment_host.html");
		target.search = window.location.search;
		window.location.replace(target.href);
		return;
	}

	const CONDITIONS = {
		baseline: {
			short: "Full view",
			label: "Baseline · Full multimodal view",
			description: "All available modalities are intentionally present.",
		},
		no_audio: {
			short: "Narration omitted",
			label: "Condition A · No narration",
			description: "Narration audio is intentionally omitted in this condition.",
		},
		no_gestures: {
			short: "Gestures omitted",
			label: "Condition B · No gestures",
			description: "The virtual hand and gesture information are intentionally omitted.",
		},
		no_objects: {
			short: "Objects omitted",
			label: "Condition C · No objects",
			description: "External objects and tools are intentionally omitted.",
		},
		no_sand: {
			short: "Sand omitted",
			label: "Condition D · No sand surface",
			description: "The reconstructed sand surface is intentionally omitted.",
		},
		stage2: {
			short: "Relations visible",
			label: "Stage 2 · Explicit relations",
			description: "All modalities and available cross-modal relations are present.",
		},
	};

	const STAGE_ONE_CONDITIONS = [
		"baseline",
		"no_audio",
		"no_gestures",
		"no_objects",
		"no_sand",
	];

	const STEPS = [
		{ id: "information", label: "Study information" },
		{ id: "profile", label: "Background" },
		{ id: "training", label: "Viewer training" },
		{ id: "task", label: "Interpretation task" },
		{ id: "questionnaire", label: "Experience and workload" },
		{ id: "complete", label: "Complete" },
	];

	const FALLBACK_PROTOCOL = {
		schemaVersion: 1,
		id: "sandstories_proposal_v1",
		title: "Digitising Sand Stories",
		trainingTasks: [
			"Play, pause, and seek on the timeline.",
			"Inspect the scene from both top and 3D views.",
			"Toggle at least one available modality.",
		],
		stage2TrainingTasks: [
			"Retrieve information hidden from the current camera angle.",
			"Inspect the reconstructed sand relief without RGB colour.",
			"Use hand motion and available relations to identify a target.",
		],
	};

	const PILOT_STAGE_ONE_QUESTIONS = [
		{
			id: "dominant_pattern",
			type: "choice",
			prompt: (
				"Near the end of the session, which spatial pattern is most "
				+ "prominent on the sand surface?"
			),
			options: [
				"Several nested curved traces",
				"A single straight divider",
				"Several isolated points",
				"No persistent surface trace",
			],
			evidencePrompt: (
				"Describe the moment, view, or modality that supports your choice."
			),
		},
		{
			id: "drawing_sequence",
			type: "choice",
			prompt: "How does the central trace appear to be produced over time?",
			options: [
				"Progressively through repeated nearby strokes",
				"All at once without visible hand motion",
				"By placing a set of external objects",
				"The sequence is unclear from the available information",
			],
			evidencePrompt: (
				"Explain how you inferred the sequence and mark the strongest moment."
			),
		},
	];

	const PILOT_STAGE_TWO_QUESTIONS = [
		{
			id: "gesture_trace_relation",
			type: "short",
			prompt: (
				"Identify one moment when the hand movement and a newly visible "
				+ "surface trace jointly clarify the drawing sequence."
			),
			evidencePrompt: (
				"Describe the relation and mark the strongest timestamped evidence."
			),
		},
		{
			id: "spatial_relation",
			type: "short",
			prompt: (
				"How do the spatial relations among the visible traces affect "
				+ "your interpretation of the session?"
			),
			evidencePrompt: (
				"State which view, layer, or explicit relation you relied on."
			),
		},
	];

	const query = new URLSearchParams(window.location.search);
	const requestedStage = query.get("stage") || query.get("study") || "stage1";
	const stage = requestedStage === "stage2" ? "stage2" : "stage1";
	const researcherMode = query.get("researcher") === "1";
	const requestedCondition = query.get("condition");

	const defaultSession = new URL(
		"assets/processed_sessions/"
		+ "session_kinect_20260623_154953_"
		+ "virtual_hand_v21b_casper5b_shadow_rgb_only_probe_f040_124/"
		+ "session.json",
		window.location.href,
	).href;
	const initialSession = query.get("session") || defaultSession;
	const trainingSession = query.get("training_session") || initialSession;

	const elements = {
		frame: document.getElementById("godot-frame"),
		viewerCard: document.querySelector(".viewer-card"),
		viewerLoading: document.getElementById("viewer-loading"),
		viewerControls: document.getElementById("viewer-controls"),
		status: document.getElementById("bridge-status"),
		title: document.getElementById("session-title"),
		conditionChip: document.getElementById("condition-chip"),
		playButton: document.getElementById("play-toggle"),
		playLabel: document.querySelector("#play-toggle .play-label"),
		timeline: document.getElementById("timeline"),
		timeLabel: document.getElementById("time-label"),
		form: document.getElementById("study-form"),
		taskContent: document.getElementById("task-content"),
		validation: document.getElementById("validation-message"),
		back: document.getElementById("back-step"),
		next: document.getElementById("next-step"),
		stageLabel: document.getElementById("stage-label"),
		stepLabel: document.getElementById("step-label"),
		progressCount: document.getElementById("progress-count"),
		progressPercent: document.getElementById("progress-percent"),
		progressBar: document.getElementById("progress-bar"),
		researcherToggle: document.getElementById("researcher-toggle"),
		researcherPanel: document.getElementById("researcher-panel"),
		researcherClose: document.getElementById("researcher-close"),
		researcherStage: document.getElementById("researcher-stage"),
		condition: document.getElementById("condition"),
		sessionUrl: document.getElementById("session-url"),
		loadSession: document.getElementById("load-session"),
		mapBlend: document.getElementById("map-blend"),
		mapBlendValue: document.getElementById("map-blend-value"),
		downloadResponse: document.getElementById("download-response"),
		resetStudy: document.getElementById("reset-study"),
		eventLog: document.getElementById("event-log"),
		eventCount: document.getElementById("event-count"),
		toast: document.getElementById("toast"),
	};

	const layerInputs = Array.from(document.querySelectorAll("[data-layer]"));
	const viewButtons = Array.from(document.querySelectorAll("[data-view]"));
	const pending = new Map();
	let sequence = 0;
	let timelineDragging = false;
	let toastTimer = 0;

	const study = {
		stage,
		researcherMode,
		stepIndex: 0,
		stepStartedAt: Date.now(),
		phaseDurationsMs: {},
		runId: makeRunId(),
		fixedCondition: (
			requestedCondition in CONDITIONS ? requestedCondition : ""
		),
		condition: stage === "stage2" ? "stage2" : "baseline",
		participantCode: query.get("participant") || "",
		protocol: FALLBACK_PROTOCOL,
		sessionUrl: initialSession,
		trainingSessionUrl: trainingSession,
		session: {},
		readiness: {
			ready: false,
			warnings: ["Session metadata is still loading."],
		},
		responses: {},
		training: {},
		evidence: {},
		events: [],
		bridgeReady: false,
		latestGodotState: null,
		trainingSurfaceMaterialStrength: null,
		submitted: false,
	};

	function makeRunId() {
		const random = Math.floor(Math.random() * 1000000)
			.toString()
			.padStart(6, "0");
		return `ss-${Date.now()}-${random}`;
	}

	function escapeHtml(value) {
		return String(value ?? "")
			.replaceAll("&", "&amp;")
			.replaceAll("<", "&lt;")
			.replaceAll(">", "&gt;")
			.replaceAll("\"", "&quot;")
			.replaceAll("'", "&#039;");
	}

	function checked(value) {
		return value ? " checked" : "";
	}

	function selected(actual, expected) {
		return actual === expected ? " selected" : "";
	}

	function formatTime(seconds) {
		const safe = Number.isFinite(Number(seconds)) ? Number(seconds) : 0;
		const minutes = Math.floor(safe / 60);
		const remainder = Math.max(0, safe - (minutes * 60));
		return `${minutes}:${remainder.toFixed(1).padStart(4, "0")}`;
	}

	function formatDuration(milliseconds) {
		const seconds = Math.max(0, Math.round(milliseconds / 1000));
		if (seconds < 60) {
			return `${seconds}s`;
		}
		return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
	}

	function showToast(message) {
		window.clearTimeout(toastTimer);
		elements.toast.textContent = message;
		elements.toast.dataset.visible = "true";
		toastTimer = window.setTimeout(() => {
			elements.toast.dataset.visible = "false";
		}, 2600);
	}

	function waitFor(milliseconds) {
		return new Promise((resolve) => {
			window.setTimeout(resolve, milliseconds);
		});
	}

	function frameUrl() {
		const url = new URL("index.html", window.location.href);
		url.searchParams.set("session", study.sessionUrl);
		url.searchParams.set("autoplay", "0");
		url.searchParams.set("embed", "1");
		url.searchParams.set("parent_origin", window.location.origin);
		url.searchParams.set("study", study.stage);
		if (study.participantCode) {
			url.searchParams.set("participant", study.participantCode);
		}
		url.searchParams.set("condition", study.condition);
		const cacheKey = query.get("t");
		if (cacheKey) {
			url.searchParams.set("t", cacheKey);
		}
		return url.href;
	}

	function sendCommand(commandName, payload = {}, timeoutMs = 60000) {
		sequence += 1;
		const requestId = `host-${Date.now()}-${sequence}`;
		const result = new Promise((resolve, reject) => {
			const timeout = window.setTimeout(() => {
				pending.delete(requestId);
				reject(new Error(`Command timed out: ${commandName}`));
			}, timeoutMs);
			pending.set(requestId, { resolve, reject, timeout });
		});
		elements.frame.contentWindow.postMessage({
			type: "sandstories:command",
			requestId,
			command: commandName,
			payload,
		}, window.location.origin);
		return result;
	}

	function reportError(error) {
		const message = error?.message || String(error);
		elements.status.dataset.state = "error";
		elements.status.querySelector("span:last-child").textContent = message;
		appendRuntimeEvent(`ERROR · ${message}`);
	}

	function appendRuntimeEvent(text) {
		const lines = elements.eventLog.textContent
			.split("\n")
			.filter(Boolean);
		lines.push(text);
		while (lines.length > 60) {
			lines.shift();
		}
		elements.eventLog.textContent = lines.join("\n");
		elements.eventLog.scrollTop = elements.eventLog.scrollHeight;
		elements.eventCount.textContent = String(lines.length);
	}

	function recordStudyEvent(eventName, payload = {}) {
		const entry = {
			event: eventName,
			unixTimeMs: Date.now(),
			runId: study.runId,
			stage: study.stage,
			condition: study.condition,
			phase: STEPS[study.stepIndex].id,
			playhead: Number(study.latestGodotState?.time || 0),
			payload,
		};
		study.events.push(entry);
		const completionCount = elements.taskContent.querySelector(
			"[data-completion-events]",
		);
		if (completionCount) {
			completionCount.textContent = String(study.events.length);
		}
		appendRuntimeEvent(
			`${formatTime(entry.playhead)} · ${eventName}`,
		);
		saveDraft();
		if (study.bridgeReady) {
			sendCommand("record_host_event", entry).catch(() => {});
		}
	}

	function storageKey() {
		const participant = study.participantCode || "local-pilot";
		return `sandstories:study:${study.stage}:${participant}`;
	}

	function saveDraft() {
		const draft = {
			schemaVersion: 1,
			runId: study.runId,
			stage: study.stage,
			condition: study.condition,
			participantCode: study.participantCode,
			stepIndex: study.stepIndex,
			responses: study.responses,
			training: study.training,
			evidence: study.evidence,
			events: study.events,
			phaseDurationsMs: study.phaseDurationsMs,
		};
		try {
			window.localStorage.setItem(storageKey(), JSON.stringify(draft));
		} catch (_error) {
			// The downloadable package remains available when storage is blocked.
		}
	}

	function loadDraft() {
		if (!study.participantCode) {
			return;
		}
		try {
			const raw = window.localStorage.getItem(storageKey());
			if (!raw) {
				return;
			}
			const draft = JSON.parse(raw);
			if (draft.stage !== study.stage || draft.participantCode !== study.participantCode) {
				return;
			}
			study.runId = String(draft.runId || study.runId);
			study.condition = String(draft.condition || study.condition);
			study.stepIndex = Math.min(
				Math.max(Number(draft.stepIndex || 0), 0),
				STEPS.length - 1,
			);
			study.responses = draft.responses || {};
			study.training = draft.training || {};
			study.evidence = draft.evidence || {};
			study.events = Array.isArray(draft.events) ? draft.events : [];
			study.phaseDurationsMs = draft.phaseDurationsMs || {};
			showToast("Saved pilot response restored");
		} catch (_error) {
			// Ignore stale or incompatible drafts.
		}
	}

	async function fetchJson(url) {
		const response = await fetch(url, { cache: "no-store" });
		if (!response.ok) {
			throw new Error(`${response.status} while loading ${url}`);
		}
		return response.json();
	}

	function evaluateReadiness(session) {
		const sources = session?.data_sources || {};
		const experiment = session?.experiment || {};
		const hasSand = Boolean(
			sources.processed_manifest
			|| sources.depth_map
			|| sources.detail_depth_map
		);
		const hasGestures = Boolean(
			session?.gesture_events?.length
			|| session?.mano_rgbd_full_sequence
			|| session?.hand_track
		);
		const hasObjects = Boolean(session?.objects?.length);
		const hasAudio = Boolean(sources.audio);
		const hasAnnotations = Boolean(
			session?.annotations?.length
			|| session?.surface_regions?.length
			|| session?.references?.length
		);
		const hasValidatedContent = Boolean(experiment.readyForDataCollection);
		const warnings = [];
		if (!hasSand) {
			warnings.push("No reconstructed sand modality.");
		}
		if (!hasGestures) {
			warnings.push("No virtual-hand or gesture modality.");
		}
		if (!hasObjects) {
			warnings.push("No external-object modality.");
		}
		if (!hasAudio) {
			warnings.push("No narration audio; the no-audio contrast is invalid.");
		}
		if (study.stage === "stage2" && !hasAnnotations) {
			warnings.push("Stage 2 needs validated annotations and referential links.");
		}
		if (!hasValidatedContent) {
			warnings.push("Creator-validated questions and answer key are not attached.");
		}
		return {
			ready: (
				hasSand
				&& hasGestures
				&& hasObjects
				&& hasAudio
				&& hasValidatedContent
				&& (study.stage !== "stage2" || hasAnnotations)
			),
			warnings,
			modalities: {
				sand: hasSand,
				gestures: hasGestures,
				objects: hasObjects,
				audio: hasAudio,
				annotations: hasAnnotations,
			},
		};
	}

	async function loadStudyMetadata() {
		const results = await Promise.allSettled([
			fetchJson(new URL("experiment_protocol.json", window.location.href)),
			fetchJson(study.sessionUrl),
		]);
		if (results[0].status === "fulfilled") {
			study.protocol = results[0].value;
		}
		if (results[1].status === "fulfilled") {
			study.session = results[1].value;
			study.readiness = evaluateReadiness(study.session);
			if (study.session.title) {
				elements.title.textContent = study.session.title;
			}
		} else {
			study.readiness = {
				ready: false,
				warnings: ["The host could not read the session metadata."],
			};
		}
		renderStep();
	}

	function conditionForPhase() {
		if (study.stage === "stage2") {
			return "stage2";
		}
		if (STEPS[study.stepIndex].id === "training") {
			return "baseline";
		}
		if (study.stepIndex < STEPS.findIndex((item) => item.id === "task")) {
			return "baseline";
		}
		return study.condition;
	}

	function deterministicCondition(participantCode) {
		if (study.stage === "stage2") {
			return "stage2";
		}
		if (study.fixedCondition in CONDITIONS && study.fixedCondition !== "stage2") {
			return study.fixedCondition;
		}
		const text = `${participantCode}:${study.protocol.id || "sandstories"}`;
		let hash = 2166136261;
		for (let index = 0; index < text.length; index += 1) {
			hash ^= text.charCodeAt(index);
			hash = Math.imul(hash, 16777619);
		}
		return STAGE_ONE_CONDITIONS[(hash >>> 0) % STAGE_ONE_CONDITIONS.length];
	}

	async function applyCondition(conditionName, logChange = false) {
		if (!(conditionName in CONDITIONS)) {
			return;
		}
		study.condition = conditionName;
		updateConditionPresentation();
		if (!study.bridgeReady) {
			return;
		}
		try {
			await sendCommand("set_condition", { condition: conditionName });
			if (logChange) {
				recordStudyEvent("condition_applied", {
					condition: conditionName,
					assignmentMethod: (
						study.fixedCondition ? "fixed" : "deterministic_random"
					),
				});
			}
		} catch (error) {
			reportError(error);
		}
	}

	function updateConditionPresentation() {
		const activeCondition = conditionForPhase();
		const meta = CONDITIONS[activeCondition] || CONDITIONS.baseline;
		const training = STEPS[study.stepIndex].id === "training";
		elements.conditionChip.textContent = training
			? "Training · Full view"
			: meta.label;
		elements.conditionChip.dataset.condition = training
			? "baseline"
			: activeCondition;
		elements.condition.value = activeCondition;
		applyLayerLocks(activeCondition);
	}

	function applyLayerLocks(conditionName) {
		const removedLayers = {
			no_audio: ["audio"],
			no_gestures: ["gestures"],
			no_objects: ["objects"],
			no_sand: ["sand", "heightmap_surface"],
		}[conditionName] || [];
		for (const input of layerInputs) {
			const unavailable = (
				study.readiness.modalities
				&& input.dataset.layer in study.readiness.modalities
				&& !study.readiness.modalities[input.dataset.layer]
			);
			const annotationLocked = (
				input.dataset.layer === "annotations"
				&& study.stage !== "stage2"
			);
			input.disabled = (
				removedLayers.includes(input.dataset.layer)
				|| annotationLocked
				|| unavailable
			);
		}
	}

	function updateGodotState(nextState) {
		study.latestGodotState = nextState;
		if (nextState.sessionTitle) {
			elements.title.textContent = nextState.sessionTitle;
		}
		const playing = Boolean(nextState.playing);
		elements.playButton.dataset.playing = String(playing);
		elements.playButton.setAttribute(
			"aria-label",
			playing ? "Pause session" : "Play session",
		);
		elements.playLabel.textContent = playing ? "Pause" : "Play";
		if (!timelineDragging) {
			elements.timeline.value = String(
				Math.round(Number(nextState.progress || 0) * 1000),
			);
		}
		elements.timeLabel.textContent = (
			`${formatTime(nextState.time)} / ${formatTime(nextState.duration)}`
		);
		const strength = Number(nextState.surface?.material_strength ?? 0.65);
		elements.mapBlend.value = String(strength);
		elements.mapBlendValue.textContent = strength.toFixed(2);
		for (const input of layerInputs) {
			input.checked = Boolean(nextState.layers?.[input.dataset.layer]);
		}
		updateViewerAvailability();
	}

	function updateViewerAvailability() {
		const phase = STEPS[study.stepIndex].id;
		const interactive = (
			study.bridgeReady
			&& ["training", "task", "questionnaire"].includes(phase)
		);
		elements.viewerControls.disabled = !interactive;
		elements.playButton.disabled = !interactive;
		elements.timeline.disabled = !interactive;
		applyLayerLocks(conditionForPhase());
	}

	function renderProgress() {
		const step = STEPS[study.stepIndex];
		const percentage = Math.round(
			((study.stepIndex + 1) / STEPS.length) * 100,
		);
		elements.stageLabel.textContent = study.stage === "stage2"
			? "Stage 2 · In-person study"
			: "Stage 1 · Online study";
		elements.stepLabel.textContent = step.label;
		elements.progressCount.textContent = (
			`Step ${study.stepIndex + 1} of ${STEPS.length}`
		);
		elements.progressPercent.textContent = `${percentage}%`;
		elements.progressBar.style.width = `${percentage}%`;
		elements.back.disabled = study.stepIndex === 0;
		elements.back.hidden = step.id === "complete";
		elements.next.hidden = step.id === "complete";
		elements.next.innerHTML = study.stepIndex === STEPS.length - 2
			? "Submit responses <span aria-hidden=\"true\">→</span>"
			: "Continue <span aria-hidden=\"true\">→</span>";
	}

	function renderInformation() {
		const stageTwo = study.stage === "stage2";
		const data = study.responses.information || {};
		return `
			<p class="task-kicker">${stageTwo ? "Observational study" : "Online study"}</p>
			<h2>Understanding a sand drawing</h2>
			<p class="task-lead">
				This study examines how the sand surface, hand gestures, narration,
				external objects, and their relationships shape interpretation.
				${stageTwo
					? "You will be asked to think aloud while using the viewer."
					: "There is no time limit; explore the session until you are confident."}
			</p>
			<div class="notice warning">
				<strong>Pilot research interface</strong>
				This page implements the procedure described in the proposal. Final
				participant information and consent language must be replaced by the
				ethics-approved documents before data collection.
			</div>
			<div class="form-section">
				<h3>What will happen</h3>
				<p class="section-help">
					You will learn the viewer, inspect one sand drawing session,
					answer comprehension questions, identify your evidence, and rate
					your experience.
				</p>
				<label class="consent-box">
					<input
						type="checkbox"
						name="consent"
						value="yes"
						${checked(data.consent === "yes")}
					>
					<span>
						I have read the study information above, understand that
						participation is voluntary, and agree to continue with this
						pilot run.
					</span>
				</label>
			</div>
		`;
	}

	function renderProfile() {
		const data = study.responses.profile || {};
		const stageTwo = study.stage === "stage2";
		return `
			<p class="task-kicker">Background questionnaire</p>
			<h2>About your experience</h2>
			<p class="task-lead">
				Use an anonymous code. Do not enter your name, email address, or
				other identifying information.
			</p>
			<label class="field-label" for="participant-code">
				Anonymous participant code
			</label>
			<input
				id="participant-code"
				type="text"
				name="participantCode"
				value="${escapeHtml(data.participantCode || study.participantCode)}"
				placeholder="e.g. P-042"
				autocomplete="off"
			>
			<div class="field-grid">
				<div>
					<label class="field-label" for="age-range">Age range</label>
					<select id="age-range" name="ageRange">
						<option value="">Select an option</option>
						<option value="18-24"${selected(data.ageRange, "18-24")}>18–24</option>
						<option value="25-34"${selected(data.ageRange, "25-34")}>25–34</option>
						<option value="35-44"${selected(data.ageRange, "35-44")}>35–44</option>
						<option value="45-54"${selected(data.ageRange, "45-54")}>45–54</option>
						<option value="55+"${selected(data.ageRange, "55+")}>55+</option>
						<option value="prefer_not"${selected(data.ageRange, "prefer_not")}>
							Prefer not to say
						</option>
					</select>
				</div>
				<div>
					<label class="field-label" for="gender">Gender (optional)</label>
					<select id="gender" name="gender">
						<option value="">Prefer not to say</option>
						<option value="woman"${selected(data.gender, "woman")}>Woman</option>
						<option value="man"${selected(data.gender, "man")}>Man</option>
						<option value="non_binary"${selected(data.gender, "non_binary")}>
							Non-binary
						</option>
						<option value="self_described"${selected(data.gender, "self_described")}>
							Self-described
						</option>
					</select>
				</div>
			</div>
			<label class="field-label" for="sand-experience">
				Experience with sand drawing practices
			</label>
			<select id="sand-experience" name="sandExperience">
				<option value="">Select an option</option>
				<option value="none"${selected(data.sandExperience, "none")}>None</option>
				<option value="seen"${selected(data.sandExperience, "seen")}>Seen it before</option>
				<option value="occasional"${selected(data.sandExperience, "occasional")}>
					Occasional experience
				</option>
				<option value="practitioner"${selected(data.sandExperience, "practitioner")}>
					Regular practitioner
				</option>
				<option value="expert"${selected(data.sandExperience, "expert")}>
					Expert or researcher
				</option>
			</select>
			<label class="field-label" for="analysis-experience">
				Experience with multimodal analysis tools
			</label>
			<select id="analysis-experience" name="analysisExperience">
				<option value="">Select an option</option>
				<option value="none"${selected(data.analysisExperience, "none")}>None</option>
				<option value="familiar"${selected(data.analysisExperience, "familiar")}>
					Some familiarity
				</option>
				<option value="regular"${selected(data.analysisExperience, "regular")}>
					Regular use
				</option>
				<option value="expert"${selected(data.analysisExperience, "expert")}>
					Professional or research expert
				</option>
			</select>
			${stageTwo ? `
				<label class="field-label" for="participant-group">
					Stage 2 participant group
				</label>
				<select id="participant-group" name="participantGroup">
					<option value="">Select an option</option>
					<option value="non_expert"${selected(data.participantGroup, "non_expert")}>
						Non-expert
					</option>
					<option value="practitioner"${selected(data.participantGroup, "practitioner")}>
						Practitioner
					</option>
					<option value="expert"${selected(data.participantGroup, "expert")}>
						Expert
					</option>
				</select>
			` : ""}
		`;
	}

	function trainingItems() {
		if (study.stage === "stage2") {
			return [
				{
					id: "occlusion",
					title: "Look behind a surface ridge",
					detail: "Watch the viewer move from above to an oblique angle, then inspect the orange target.",
					action: "orbit",
					button: "Show the viewpoint change",
				},
				{
					id: "segmentation",
					title: "Read the surface relief",
					detail: "Temporarily remove RGB colour and use lighting to identify physical height changes.",
					action: "depth",
					button: "Show relief only",
				},
				{
					id: "referential",
					title: "Connect action and trace",
					detail: "Follow one moment where hand motion, time, and a relation cue form a single piece of evidence.",
					action: "relation",
					button: "Show the linked moment",
				},
			];
		}
		return [
			{
				id: "playback",
				title: "Watch the action unfold",
				detail: "The viewer will play a short sample. Follow the virtual hand and the orange target on the sand.",
				action: "play",
				button: "Play guided sample",
			},
			{
				id: "camera",
				title: "Compare two viewpoints",
				detail: "Watch the same trace first from above and then from an oblique 3D view.",
				action: "orbit",
				button: "Show both views",
			},
			{
				id: "layers",
				title: "Separate the information",
				detail: "Hide and restore the virtual hand, then notice what the sand surface alone can tell you.",
				action: "layer",
				button: "Compare the layers",
			},
		];
	}

	function currentTrainingIndex() {
		return trainingItems().findIndex((item) => !study.training[item.id]);
	}

	function currentTrainingItem() {
		const index = currentTrainingIndex();
		return index >= 0 ? trainingItems()[index] : null;
	}

	function clearTrainingFocus() {
		delete elements.viewerCard.dataset.trainingFocus;
	}

	async function syncTrainingGuide() {
		const inTraining = STEPS[study.stepIndex].id === "training";
		const item = inTraining ? currentTrainingItem() : null;
		if (!item) {
			clearTrainingFocus();
			if (study.bridgeReady) {
				await sendCommand("set_training_guide", {
					mode: "off",
				}).catch(() => {});
			}
			return;
		}
		elements.viewerCard.dataset.trainingFocus = item.id;
		if (study.trainingSurfaceMaterialStrength === null) {
			study.trainingSurfaceMaterialStrength = Number(
				study.latestGodotState?.surface?.material_strength ?? 0.65,
			);
		}
		if (study.bridgeReady) {
			await sendCommand("set_training_guide", {
				mode: item.id,
				step: currentTrainingIndex() + 1,
				total: trainingItems().length,
			}).catch(reportError);
		}
	}

	async function restoreTrainingVisualState() {
		clearTrainingFocus();
		if (!study.bridgeReady) {
			return;
		}
		await sendCommand("set_training_guide", { mode: "off" }).catch(() => {});
		await sendCommand("set_playing", { playing: false }).catch(() => {});
		await sendCommand("set_surface_control", {
			key: "material_strength",
			value: Number(study.trainingSurfaceMaterialStrength ?? 0.65),
		}).catch(() => {});
		await sendCommand("set_layer", {
			layer: "gestures",
			visible: true,
		}).catch(() => {});
		await sendCommand("set_view", { preset: "orbit" }).catch(() => {});
	}

	function renderTraining() {
		const items = trainingItems();
		const activeIndex = currentTrainingIndex();
		const allComplete = activeIndex < 0;
		return `
			<p class="task-kicker">Guided practice</p>
			<h2>${allComplete ? "Practice complete" : `Follow step ${activeIndex + 1}`}</h2>
			<p class="task-lead">
				Training uses the complete representation. Work through one highlighted
				action at a time; the Godot scene will point to what you should watch.
			</p>
			<div class="notice guided-notice">
				<strong>${allComplete ? "Ready for the main task" : "Look in both places"}</strong>
				${allComplete
					? "The tutorial overlay will be removed before the assigned condition begins."
					: "The active control is highlighted below the viewer, while an orange ring inside Godot marks the area to inspect."}
			</div>
			<div class="training-list">
				${items.map((item, index) => {
					const complete = Boolean(study.training[item.id]);
					const active = index === activeIndex;
					const locked = !complete && !active;
					return `
						<div
							class="training-item"
							data-training-item="${escapeHtml(item.id)}"
							data-complete="${complete}"
							data-active="${active}"
							data-locked="${locked}"
						>
							<span class="training-index">${complete ? "✓" : index + 1}</span>
							<span>
								<strong>${escapeHtml(item.title)}</strong>
								<small>${escapeHtml(item.detail)}</small>
							</span>
							<button
								class="training-action"
								type="button"
								data-training-action="${escapeHtml(item.action)}"
								data-training-id="${escapeHtml(item.id)}"
								${active ? "" : "disabled"}
							>
								${complete ? "Done" : locked ? "Complete earlier step" : escapeHtml(item.button)}
							</button>
						</div>
					`;
				}).join("")}
			</div>
		`;
	}

	function currentQuestions() {
		const experiment = study.session?.experiment || {};
		const key = study.stage === "stage2"
			? "stage2Questions"
			: "stage1Questions";
		if (Array.isArray(experiment[key]) && experiment[key].length) {
			return experiment[key];
		}
		return study.stage === "stage2"
			? PILOT_STAGE_TWO_QUESTIONS
			: PILOT_STAGE_ONE_QUESTIONS;
	}

	function renderQuestion(question, index, data) {
		const questionId = String(question.id || `question_${index + 1}`);
		const answerName = `answer:${questionId}`;
		const evidenceName = `evidence:${questionId}`;
		const answer = data[answerName] || "";
		const evidence = data[evidenceName] || "";
		const snapshot = study.evidence[questionId];
		let answerControl = "";
		if (question.type === "choice") {
			answerControl = `
				<div class="radio-list">
					${(question.options || []).map((option) => `
						<label class="choice-card">
							<input
								type="radio"
								name="${escapeHtml(answerName)}"
								value="${escapeHtml(option)}"
								${checked(answer === option)}
							>
							<span>${escapeHtml(option)}</span>
						</label>
					`).join("")}
				</div>
			`;
		} else {
			answerControl = `
				<textarea
					name="${escapeHtml(answerName)}"
					placeholder="Write your answer here…"
				>${escapeHtml(answer)}</textarea>
			`;
		}
		return `
			<section class="question-block">
				<span class="question-number">Question ${index + 1}</span>
				<p class="question-prompt">${escapeHtml(question.prompt)}</p>
				${answerControl}
				<label class="field-label" for="evidence-${escapeHtml(questionId)}">
					Your evidence
				</label>
				<textarea
					id="evidence-${escapeHtml(questionId)}"
					name="${escapeHtml(evidenceName)}"
					placeholder="${escapeHtml(
						question.evidencePrompt
						|| "Explain what in the representation supports your answer.",
					)}"
				>${escapeHtml(evidence)}</textarea>
				<div class="evidence-row">
					<button
						class="evidence-button"
						type="button"
						data-evidence-question="${escapeHtml(questionId)}"
					>
						Mark current view
					</button>
					<span class="evidence-state" data-evidence-state="${escapeHtml(questionId)}">
						${snapshot
							? `Marked at ${formatTime(snapshot.playhead)}`
							: "No timestamp marked"}
					</span>
				</div>
			</section>
		`;
	}

	function renderTask() {
		const data = study.responses.task || {};
		const questions = currentQuestions();
		const experiment = study.session?.experiment || {};
		const summaryPrompt = experiment.summaryPrompt || (
			"Summarise what the drawing communicates and describe the sequence "
			+ "of actions that led to your interpretation."
		);
		const condition = CONDITIONS[study.condition] || CONDITIONS.baseline;
		const thinkAloud = study.stage === "stage2";
		const pilotNotice = !study.readiness.ready
			? `
				<div class="notice warning">
					<strong>Pilot task set — not ready for research data</strong>
					${escapeHtml(study.readiness.warnings.join(" "))}
					The prompts below test the workflow; they require creator validation
					before deployment.
				</div>
			`
			: "";
		return `
			<p class="task-kicker">Main interpretation task</p>
			<h2>Explore, interpret, and show your evidence</h2>
			<p class="task-lead">
				Replay and inspect the session for as long as you need.
				${thinkAloud
					? "Please keep describing what you notice, infer, and find uncertain."
					: "Complete every question when you feel confident."}
			</p>
			<div class="notice">
				<strong>${escapeHtml(condition.label)}</strong>
				${escapeHtml(condition.description)}
			</div>
			${pilotNotice}
			<div class="form-section">
				<h3>Session summary</h3>
				<p class="section-help">${escapeHtml(summaryPrompt)}</p>
				<textarea
					name="summary"
					placeholder="Write a concise summary of your interpretation…"
				>${escapeHtml(data.summary || "")}</textarea>
			</div>
			${questions.map((question, index) => (
				renderQuestion(question, index, data)
			)).join("")}
		`;
	}

	function renderLikert(name, prompt, data, low = "Strongly disagree", high = "Strongly agree") {
		return `
			<div class="form-section">
				<h3>${escapeHtml(prompt)}</h3>
				<div class="likert-scale" role="radiogroup" aria-label="${escapeHtml(prompt)}">
					${Array.from({ length: 7 }, (_, index) => index + 1).map((value) => `
						<label class="likert-option">
							<input
								type="radio"
								name="${escapeHtml(name)}"
								value="${value}"
								${checked(String(data[name] || "") === String(value))}
							>
							<span>${value}</span>
						</label>
					`).join("")}
				</div>
				<div class="scale-ends"><span>${low}</span><span>${high}</span></div>
			</div>
		`;
	}

	function renderTlxItem(name, label, data) {
		const fieldName = `nasa:${name}`;
		const value = Number(data[fieldName] ?? 50);
		return `
			<div class="tlx-item">
				<label class="range-label" for="tlx-${escapeHtml(name)}">
					<span>${escapeHtml(label)}</span>
					<output data-range-output="${escapeHtml(fieldName)}">${value}</output>
				</label>
				<input
					id="tlx-${escapeHtml(name)}"
					type="range"
					name="${escapeHtml(fieldName)}"
					min="0"
					max="100"
					step="5"
					value="${value}"
				>
			</div>
		`;
	}

	function renderQuestionnaire() {
		const data = study.responses.questionnaire || {};
		const relied = Array.isArray(data.modalitiesReliedOn)
			? data.modalitiesReliedOn
			: [data.modalitiesReliedOn].filter(Boolean);
		return `
			<p class="task-kicker">Post-task questionnaire</p>
			<h2>Your experience</h2>
			<p class="task-lead">
				These ratings capture confidence, usability, perceived difficulty,
				information reliance, and unweighted NASA-TLX workload.
			</p>
			${renderLikert(
				"confidence",
				"I am confident in my interpretation.",
				data,
			)}
			${renderLikert(
				"difficulty",
				"The interpretation task was difficult.",
				data,
			)}
			${renderLikert(
				"ease",
				"The interactive viewer was easy to use.",
				data,
			)}
			<div class="form-section">
				<h3>Which information did you rely on?</h3>
				<p class="section-help">Select all that contributed to your answers.</p>
				<div class="check-list">
					${[
						["sand", "Sand surface"],
						["gestures", "Virtual hand and gestures"],
						["audio", "Narration audio"],
						["objects", "External objects"],
						["annotations", "Annotations and referential links"],
					].map(([value, label]) => `
						<label class="choice-card">
							<input
								type="checkbox"
								name="modalitiesReliedOn"
								value="${value}"
								${checked(relied.includes(value))}
							>
							<span>${label}</span>
						</label>
					`).join("")}
				</div>
			</div>
			<div class="form-section">
				<h3>NASA-TLX workload</h3>
				<p class="section-help">
					0 means very low and 100 means very high. For performance,
					0 means perfect and 100 means failure.
				</p>
				<div class="tlx-grid">
					${renderTlxItem("mentalDemand", "Mental demand", data)}
					${renderTlxItem("physicalDemand", "Physical demand", data)}
					${renderTlxItem("temporalDemand", "Temporal demand", data)}
					${renderTlxItem("performance", "Performance", data)}
					${renderTlxItem("effort", "Effort", data)}
					${renderTlxItem("frustration", "Frustration", data)}
				</div>
			</div>
			${study.stage === "stage2" ? `
				${renderLikert(
					"annotationUsefulness",
					"The explicit annotations and referential links were useful.",
					data,
				)}
				<div class="form-section">
					<h3>Uncertainty and information-seeking</h3>
					<p class="section-help">
						Record moments of uncertainty, useful relations, or strategies
						mentioned during think-aloud. The researcher can expand these
						notes during the semi-structured interview.
					</p>
					<textarea
						name="uncertaintyNotes"
						placeholder="What felt uncertain? What information resolved it?"
					>${escapeHtml(data.uncertaintyNotes || "")}</textarea>
				</div>
			` : `
				<div class="form-section">
					<h3>Anything else?</h3>
					<textarea
						name="comments"
						placeholder="Optional comments about the viewer or task…"
					>${escapeHtml(data.comments || "")}</textarea>
				</div>
			`}
		`;
	}

	function renderComplete() {
		const payload = submissionPayload();
		const totalMs = Object.values(payload.phaseDurationsMs)
			.reduce((sum, value) => sum + Number(value || 0), 0);
		return `
			<div class="completion">
				<div class="completion-mark" aria-hidden="true">✓</div>
				<p class="task-kicker">Response package prepared</p>
				<h2>Thank you</h2>
				<p class="task-lead">
					This pilot run is complete. The package includes the assigned
					condition, task responses, evidence snapshots, questionnaire,
					phase timing, and interaction events.
				</p>
				<div class="completion-summary">
					<div>
						<span>Run</span>
						<strong>${escapeHtml(study.runId.slice(-10))}</strong>
					</div>
					<div>
						<span>Condition</span>
						<strong>${escapeHtml(CONDITIONS[study.condition].short)}</strong>
					</div>
					<div>
						<span>Duration</span>
						<strong>${formatDuration(totalMs)}</strong>
					</div>
					<div>
						<span>Runtime events</span>
						<strong data-completion-events>${study.events.length}</strong>
					</div>
				</div>
				<div class="completion-actions">
					<button class="primary-button full-width" type="button" data-complete-action="download">
						Download anonymous response
					</button>
					<button class="secondary-button full-width" type="button" data-complete-action="restart">
						Start another pilot run
					</button>
				</div>
			</div>
		`;
	}

	function renderStep() {
		const step = STEPS[study.stepIndex];
		const renderers = {
			information: renderInformation,
			profile: renderProfile,
			training: renderTraining,
			task: renderTask,
			questionnaire: renderQuestionnaire,
			complete: renderComplete,
		};
		elements.taskContent.innerHTML = renderers[step.id]();
		elements.validation.textContent = "";
		renderProgress();
		updateConditionPresentation();
		updateViewerAvailability();
		bindDynamicActions();
		elements.taskContent.scrollTop = 0;
		if (step.id === "training") {
			syncTrainingGuide().catch(reportError);
		} else {
			clearTrainingFocus();
		}
	}

	function collectCurrentForm() {
		const step = STEPS[study.stepIndex].id;
		if (["training", "complete"].includes(step)) {
			return;
		}
		const data = {};
		const formData = new FormData(elements.form);
		for (const [key, value] of formData.entries()) {
			if (key in data) {
				data[key] = Array.isArray(data[key])
					? [...data[key], value]
					: [data[key], value];
			} else {
				data[key] = value;
			}
		}
		study.responses[step] = data;
		if (step === "profile") {
			study.participantCode = String(data.participantCode || "").trim();
		}
		saveDraft();
	}

	function validateCurrentStep() {
		collectCurrentForm();
		const step = STEPS[study.stepIndex].id;
		const data = study.responses[step] || {};
		if (step === "information" && data.consent !== "yes") {
			return "Please confirm that you have read the pilot study information.";
		}
		if (step === "profile") {
			if (!String(data.participantCode || "").trim()) {
				return "Enter an anonymous participant code.";
			}
			if (!data.ageRange || !data.sandExperience || !data.analysisExperience) {
				return "Complete the required background fields.";
			}
			if (study.stage === "stage2" && !data.participantGroup) {
				return "Select the Stage 2 participant group.";
			}
		}
		if (step === "training") {
			const incomplete = trainingItems().some((item) => !study.training[item.id]);
			if (incomplete) {
				return "Complete all three viewer training actions before continuing.";
			}
		}
		if (step === "task") {
			if (String(data.summary || "").trim().length < 20) {
				return "Write a slightly fuller session summary before continuing.";
			}
			for (const question of currentQuestions()) {
				const questionId = String(question.id);
				if (!String(data[`answer:${questionId}`] || "").trim()) {
					return "Answer every comprehension question.";
				}
				if (String(data[`evidence:${questionId}`] || "").trim().length < 10) {
					return "Explain the evidence supporting every answer.";
				}
			}
		}
		if (step === "questionnaire") {
			const requiredRatings = ["confidence", "difficulty", "ease"];
			if (study.stage === "stage2") {
				requiredRatings.push("annotationUsefulness");
			}
			if (requiredRatings.some((name) => !data[name])) {
				return "Complete the required experience ratings.";
			}
			const relied = Array.isArray(data.modalitiesReliedOn)
				? data.modalitiesReliedOn
				: [data.modalitiesReliedOn].filter(Boolean);
			if (!relied.length) {
				return "Select at least one source of information you relied on.";
			}
		}
		return "";
	}

	function updatePhaseTiming() {
		const step = STEPS[study.stepIndex].id;
		const elapsed = Date.now() - study.stepStartedAt;
		study.phaseDurationsMs[step] = (
			Number(study.phaseDurationsMs[step] || 0) + elapsed
		);
	}

	async function moveToStep(nextIndex) {
		updatePhaseTiming();
		const previousPhase = STEPS[study.stepIndex].id;
		study.stepIndex = Math.min(Math.max(nextIndex, 0), STEPS.length - 1);
		study.stepStartedAt = Date.now();
		const phase = STEPS[study.stepIndex].id;
		if (previousPhase === "training" && phase !== "training") {
			await restoreTrainingVisualState();
		}
		if (phase === "training") {
			await applyCondition(
				study.stage === "stage2" ? "stage2" : "baseline",
			);
		}
		if (phase === "task") {
			study.condition = deterministicCondition(study.participantCode);
			await applyCondition(study.condition, true);
			await sendCommand("set_playing", { playing: false }).catch(() => {});
			await sendCommand("seek", { seconds: 0 }).catch(() => {});
		}
		if (phase === "questionnaire") {
			await sendCommand("set_playing", { playing: false }).catch(() => {});
		}
		if (phase === "complete" && !study.submitted) {
			study.submitted = true;
			recordStudyEvent("study_submitted", {
				readyForDataCollection: study.readiness.ready,
				questionCount: currentQuestions().length,
			});
		}
		recordStudyEvent("study_phase", { phase });
		saveDraft();
		renderStep();
	}

	function setTrainingComplete(trainingId) {
		const active = currentTrainingItem();
		if (!active || active.id !== trainingId) {
			return;
		}
		study.training[trainingId] = true;
		saveDraft();
		recordStudyEvent("training_action_completed", { trainingId });
		renderStep();
		if (trainingItems().every((entry) => study.training[entry.id])) {
			showToast("Guided practice complete");
		}
	}

	async function runTrainingAction(action, trainingId) {
		const button = elements.taskContent.querySelector(
			`[data-training-id="${CSS.escape(trainingId)}"]`,
		);
		if (button) {
			button.disabled = true;
			button.dataset.running = "true";
			button.textContent = "Watch the viewer…";
		}
		try {
			if (action === "play") {
				await sendCommand("seek", { seconds: 0 });
				await sendCommand("set_playing", { playing: true });
				await waitFor(2400);
				await sendCommand("set_playing", { playing: false });
			} else if (action === "orbit") {
				await sendCommand("set_view", { preset: "top" });
				await waitFor(700);
				await sendCommand("set_view", { preset: "orbit" });
			} else if (action === "layer") {
				await sendCommand("set_layer", { layer: "gestures", visible: false });
				await waitFor(850);
				await sendCommand("set_layer", {
					layer: "gestures",
					visible: true,
				});
			} else if (action === "depth") {
				study.trainingSurfaceMaterialStrength = Number(
					study.latestGodotState?.surface?.material_strength ?? 0.65,
				);
				await sendCommand("set_surface_control", {
					key: "material_strength",
					value: 0,
				});
				await sendCommand("set_view", { preset: "top" });
				await waitFor(1100);
			} else if (action === "relation") {
				await sendCommand("set_layer", {
					layer: "annotations",
					visible: true,
				});
				await sendCommand("set_layer", {
					layer: "gestures",
					visible: true,
				});
				await sendCommand("seek_normalized", { progress: 0.7 });
				await sendCommand("set_playing", { playing: true });
				await waitFor(1800);
				await sendCommand("set_playing", { playing: false });
			}
			setTrainingComplete(trainingId);
		} catch (error) {
			if (button) {
				button.disabled = false;
				button.dataset.running = "false";
				button.textContent = (
					trainingItems().find((item) => item.id === trainingId)?.button
					|| "Try again"
				);
			}
			reportError(error);
		}
	}

	async function markEvidence(questionId) {
		const snapshot = {
			playhead: Number(study.latestGodotState?.time || 0),
			progress: Number(study.latestGodotState?.progress || 0),
			layers: study.latestGodotState?.layers || {},
			camera: study.latestGodotState?.camera || {},
			condition: study.condition,
			capturedUnixTimeMs: Date.now(),
		};
		study.evidence[questionId] = snapshot;
		const label = elements.taskContent.querySelector(
			`[data-evidence-state="${CSS.escape(questionId)}"]`,
		);
		if (label) {
			label.textContent = `Marked at ${formatTime(snapshot.playhead)}`;
		}
		try {
			await sendCommand("mark_evidence");
			recordStudyEvent("task_evidence_attached", {
				questionId,
				snapshot,
			});
			showToast(`Evidence marked at ${formatTime(snapshot.playhead)}`);
		} catch (error) {
			reportError(error);
		}
	}

	function bindDynamicActions() {
		for (const button of elements.taskContent.querySelectorAll(
			"[data-training-action]",
		)) {
			button.addEventListener("click", () => {
				runTrainingAction(
					button.dataset.trainingAction,
					button.dataset.trainingId,
				);
			});
		}
		for (const button of elements.taskContent.querySelectorAll(
			"[data-evidence-question]",
		)) {
			button.addEventListener("click", () => {
				collectCurrentForm();
				markEvidence(button.dataset.evidenceQuestion);
			});
		}
		for (const input of elements.taskContent.querySelectorAll(
			"input[type=\"range\"]",
		)) {
			input.addEventListener("input", () => {
				const output = elements.taskContent.querySelector(
					`[data-range-output="${CSS.escape(input.name)}"]`,
				);
				if (output) {
					output.textContent = input.value;
				}
				collectCurrentForm();
			});
		}
		for (const input of elements.taskContent.querySelectorAll(
			"input, select, textarea",
		)) {
			input.addEventListener("change", collectCurrentForm);
		}
		for (const button of elements.taskContent.querySelectorAll(
			"[data-complete-action]",
		)) {
			button.addEventListener("click", () => {
				if (button.dataset.completeAction === "download") {
					downloadSubmission();
				} else {
					resetRun();
				}
			});
		}
	}

	function taskResponsesForExport() {
		const data = study.responses.task || {};
		return currentQuestions().map((question) => {
			const questionId = String(question.id);
			return {
				id: questionId,
				prompt: question.prompt,
				answer: data[`answer:${questionId}`] || "",
				evidence: data[`evidence:${questionId}`] || "",
				viewSnapshot: study.evidence[questionId] || {},
			};
		});
	}

	function questionnaireForExport() {
		const data = study.responses.questionnaire || {};
		const relied = Array.isArray(data.modalitiesReliedOn)
			? data.modalitiesReliedOn
			: [data.modalitiesReliedOn].filter(Boolean);
		const payload = {
			easeOfUseLikert: Number(data.ease || 0),
			interpretationConfidenceLikert: Number(data.confidence || 0),
			taskDifficultyLikert: Number(data.difficulty || 0),
			modalitiesReliedOn: relied,
			nasaTlxRaw: {},
			comments: data.comments || "",
		};
		for (const key of [
			"mentalDemand",
			"physicalDemand",
			"temporalDemand",
			"performance",
			"effort",
			"frustration",
		]) {
			payload.nasaTlxRaw[key] = Number(data[`nasa:${key}`] ?? 50);
		}
		if (study.stage === "stage2") {
			payload.annotationUsefulnessLikert = Number(
				data.annotationUsefulness || 0,
			);
			payload.uncertaintyNotes = data.uncertaintyNotes || "";
		}
		return payload;
	}

	function submissionPayload() {
		const timings = { ...study.phaseDurationsMs };
		if (STEPS[study.stepIndex].id !== "complete") {
			const phase = STEPS[study.stepIndex].id;
			timings[phase] = (
				Number(timings[phase] || 0)
				+ Date.now()
				- study.stepStartedAt
			);
		}
		return {
			schemaVersion: 1,
			protocolId: study.protocol.id || "sandstories_proposal_v1",
			runId: study.runId,
			stage: study.stage,
			condition: study.condition,
			assignmentMethod: study.fixedCondition
				? "fixed"
				: "client_deterministic_unbalanced",
			sessionId: study.session.id || "",
			sessionTitle: study.session.title || elements.title.textContent,
			sessionUrl: study.sessionUrl,
			readyForDataCollection: study.readiness.ready,
			readinessWarnings: study.readiness.warnings,
			participantProfile: study.responses.profile || {},
			responses: {
				summary: study.responses.task?.summary || "",
				questions: taskResponsesForExport(),
			},
			questionnaire: questionnaireForExport(),
			evidenceSnapshots: study.evidence,
			phaseDurationsMs: timings,
			interactionEvents: study.events,
			completedUnixTimeMs: Date.now(),
		};
	}

	function downloadSubmission() {
		collectCurrentForm();
		const payload = submissionPayload();
		const blob = new Blob(
			[`${JSON.stringify(payload, null, 2)}\n`],
			{ type: "application/json" },
		);
		const url = URL.createObjectURL(blob);
		const anchor = document.createElement("a");
		anchor.href = url;
		anchor.download = `${study.runId}.json`;
		document.body.append(anchor);
		anchor.click();
		anchor.remove();
		window.setTimeout(() => URL.revokeObjectURL(url), 1000);
		recordStudyEvent("response_package_downloaded", {
			filename: `${study.runId}.json`,
		});
		showToast("Anonymous response package downloaded");
	}

	function resetRun() {
		try {
			window.localStorage.removeItem(storageKey());
		} catch (_error) {
			// Continue with an in-memory reset.
		}
		const url = new URL(window.location.href);
		url.searchParams.set("t", `run-${Date.now()}`);
		window.location.assign(url.href);
	}

	async function loadSession(url) {
		study.sessionUrl = url;
		elements.status.dataset.state = "loading";
		elements.status.querySelector("span:last-child").textContent = "Loading session";
		try {
			const session = await fetchJson(url);
			await sendCommand("load_session", { url }, 120000);
			study.session = session;
			study.readiness = evaluateReadiness(session);
			elements.title.textContent = session.title || "Untitled sand drawing session";
			recordStudyEvent("host_session_loaded", {
				sessionId: session.id || "",
				url,
				readiness: study.readiness,
			});
			renderStep();
			elements.status.dataset.state = "ready";
			elements.status.querySelector("span:last-child").textContent = "Viewer ready";
			showToast("Session loaded");
		} catch (error) {
			reportError(error);
		}
	}

	function bindStaticControls() {
		elements.back.addEventListener("click", () => {
			collectCurrentForm();
			moveToStep(study.stepIndex - 1);
		});
		elements.next.addEventListener("click", () => {
			const validation = validateCurrentStep();
			if (validation) {
				elements.validation.textContent = validation;
				return;
			}
			elements.validation.textContent = "";
			recordStudyEvent("phase_completed", {
				phase: STEPS[study.stepIndex].id,
			});
			moveToStep(study.stepIndex + 1);
		});
		elements.playButton.addEventListener("click", () => {
			sendCommand("toggle_playback")
				.then(() => {
					if (STEPS[study.stepIndex].id === "training") {
						const playback = trainingItems().find(
							(item) => item.id === "playback",
						);
						if (playback) {
							setTrainingComplete(playback.id);
						}
					}
					recordStudyEvent("transport_control", {
						action: study.latestGodotState?.playing ? "pause" : "play",
					});
				})
				.catch(reportError);
		});
		elements.timeline.addEventListener("pointerdown", () => {
			timelineDragging = true;
		});
		elements.timeline.addEventListener("input", () => {
			if (!study.latestGodotState) {
				return;
			}
			const seconds = (
				Number(elements.timeline.value) / 1000
			) * Number(study.latestGodotState.duration || 0);
			elements.timeLabel.textContent = (
				`${formatTime(seconds)} / `
				+ `${formatTime(study.latestGodotState.duration)}`
			);
		});
		elements.timeline.addEventListener("change", () => {
			timelineDragging = false;
			sendCommand("seek_normalized", {
				progress: Number(elements.timeline.value) / 1000,
			})
				.then(() => {
					if (STEPS[study.stepIndex].id === "training") {
						const playback = trainingItems().find(
							(item) => item.id === "playback",
						);
						if (playback) {
							setTrainingComplete(playback.id);
						}
					}
					recordStudyEvent("timeline_seek", {
						progress: Number(elements.timeline.value) / 1000,
					});
				})
				.catch(reportError);
		});
		elements.timeline.addEventListener("pointerup", () => {
			timelineDragging = false;
		});
		for (const input of layerInputs) {
			input.addEventListener("change", () => {
				sendCommand("set_layer", {
					layer: input.dataset.layer,
					visible: input.checked,
				})
					.then(() => {
						if (STEPS[study.stepIndex].id === "training") {
							const layerTask = trainingItems().find(
								(item) => item.id === "layers",
							);
							if (layerTask) {
								setTrainingComplete(layerTask.id);
							}
						}
						recordStudyEvent("modality_toggled", {
							layer: input.dataset.layer,
							visible: input.checked,
						});
					})
					.catch(reportError);
			});
		}
		for (const button of viewButtons) {
			button.addEventListener("click", () => {
				sendCommand("set_view", { preset: button.dataset.view })
					.then(() => {
						if (STEPS[study.stepIndex].id === "training") {
							const cameraTask = trainingItems().find(
								(item) => ["camera", "occlusion"].includes(item.id),
							);
							if (cameraTask) {
								setTrainingComplete(cameraTask.id);
							}
						}
						recordStudyEvent("camera_preset", {
							preset: button.dataset.view,
						});
					})
					.catch(reportError);
			});
		}
		elements.researcherToggle.addEventListener("click", () => {
			elements.researcherPanel.hidden = false;
		});
		elements.researcherClose.addEventListener("click", () => {
			elements.researcherPanel.hidden = true;
		});
		elements.researcherStage.addEventListener("change", () => {
			const url = new URL(window.location.href);
			url.searchParams.set("stage", elements.researcherStage.value);
			url.searchParams.set("researcher", "1");
			url.searchParams.set("t", `stage-${Date.now()}`);
			window.location.assign(url.href);
		});
		elements.condition.addEventListener("change", () => {
			study.fixedCondition = elements.condition.value;
			applyCondition(elements.condition.value, true);
			renderStep();
		});
		elements.loadSession.addEventListener("click", () => {
			const url = elements.sessionUrl.value.trim();
			if (!url) {
				showToast("Enter a session URL first");
				return;
			}
			loadSession(url);
		});
		elements.mapBlend.addEventListener("input", () => {
			elements.mapBlendValue.textContent = Number(
				elements.mapBlend.value,
			).toFixed(2);
		});
		elements.mapBlend.addEventListener("change", () => {
			sendCommand("set_surface_control", {
				key: "material_strength",
				value: Number(elements.mapBlend.value),
			})
				.then(() => recordStudyEvent("surface_colour_changed", {
					value: Number(elements.mapBlend.value),
				}))
				.catch(reportError);
		});
		elements.downloadResponse.addEventListener("click", downloadSubmission);
		elements.resetStudy.addEventListener("click", resetRun);
	}

	window.addEventListener("message", (event) => {
		if (
			event.source !== elements.frame.contentWindow
			|| event.origin !== window.location.origin
		) {
			return;
		}
		const message = event.data;
		if (!message || typeof message.type !== "string") {
			return;
		}
		if (message.type === "sandstories:ready") {
			study.bridgeReady = true;
			elements.viewerLoading.hidden = true;
			elements.status.dataset.state = "ready";
			elements.status.querySelector("span:last-child").textContent = "Viewer ready";
			updateGodotState(message.detail);
			appendRuntimeEvent("READY · Godot bridge connected");
			applyCondition(conditionForPhase());
			syncTrainingGuide().catch(reportError);
			recordStudyEvent("viewer_ready", {
				sessionUrl: study.sessionUrl,
			});
			return;
		}
		if (message.type === "sandstories:state") {
			updateGodotState(message.detail);
			return;
		}
		if (message.type === "sandstories:event") {
			const detail = message.detail || {};
			appendRuntimeEvent(
				`${formatTime(detail.playhead)} · ${detail.event || "runtime_event"}`,
			);
			return;
		}
		if (message.type === "sandstories:command_result") {
			const detail = message.detail || {};
			const request = pending.get(detail.requestId);
			if (!request) {
				return;
			}
			window.clearTimeout(request.timeout);
			pending.delete(detail.requestId);
			if (detail.ok) {
				request.resolve(detail.data);
			} else {
				request.reject(new Error(detail.error || "Command failed"));
			}
		}
	});

	async function start() {
		elements.researcherToggle.hidden = !researcherMode;
		elements.researcherStage.value = study.stage;
		elements.sessionUrl.value = study.sessionUrl;
		loadDraft();
		bindStaticControls();
		renderStep();
		elements.frame.src = frameUrl();
		await loadStudyMetadata();
	}

	start().catch(reportError);
}());
