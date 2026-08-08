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
	const EXPERIMENT_API = "/api/experiment";
	const requestedStage = query.get("stage") || query.get("study") || "stage1";
	const stage = requestedStage === "stage2" ? "stage2" : "stage1";
	const researcherMode = query.get("researcher") === "1";
	const pilotMode = researcherMode || query.get("pilot") === "1";
	const requestedCondition = query.get("condition");

	const defaultSession = new URL(
		"assets/processed_sessions/"
		+ "session_kinect_20260623_154953_"
		+ "virtual_hand_v21b_casper5b_shadow_rgb_only_probe_f040_124/"
		+ "session.json",
		window.location.href,
	).href;
	const initialSession = query.get("session") || defaultSession;
	const requestedTrainingSession = query.get("training_session") || "";

	const elements = {
		frame: document.getElementById("godot-frame"),
		submissionStatus: document.getElementById("submission-status"),
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
	let navigationBusy = false;

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
		assignedCondition: stage === "stage2" ? "stage2" : "",
		participantCode: query.get("participant") || "",
		protocol: FALLBACK_PROTOCOL,
		sessionUrl: initialSession,
		trainingSessionUrl: requestedTrainingSession || initialSession,
		activeSessionUrl: initialSession,
		session: {},
		trainingSession: {},
		readiness: {
			checked: false,
			ready: false,
			warnings: ["Session metadata is still loading."],
		},
		responses: {},
		training: {},
		evidence: {},
		events: [],
		bridgeReady: false,
		latestGodotState: null,
		playback: {
			started: false,
			maxProgress: 0,
		},
		trainingSurfaceMaterialStrength: null,
		submitted: false,
		assignmentMethod: stage === "stage2" ? "server_stage2" : "pending",
		stage2Order: null,
		lastLocalSavedAt: 0,
		remote: {
			available: false,
			runId: "",
			resumeToken: "",
			revision: 0,
			eventCursor: 0,
			pendingEventBatch: null,
			saveTimer: 0,
			syncPromise: null,
			dirty: false,
			completed: false,
			lastError: "",
		},
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
		url.searchParams.set("session", study.activeSessionUrl);
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

	async function seekAndWait(seconds, timeoutMs = 12000) {
		const before = study.latestGodotState || await sendCommand("get_state");
		const target = Math.min(Math.max(Number(seconds || 0), 0), Number(
			before.duration || seconds || 0,
		));
		let state = await sendCommand("seek", { seconds: target });
		updateGodotState(state);
		const frameCount = Number(state.frameCount || 0);
		const frameInterval = Number(state.duration || 0) / Math.max(frameCount - 1, 1);
		const frameShouldChange = Boolean(
			frameCount > 1
			&& Math.abs(target - Number(before.time || 0)) > frameInterval * 1.25,
		);
		const deadline = Date.now() + timeoutMs;
		while (
			frameShouldChange
			&& Number(state.frameIndex) === Number(before.frameIndex)
			&& Date.now() < deadline
		) {
			await waitFor(100);
			state = await sendCommand("get_state");
			updateGodotState(state);
		}
		if (
			frameShouldChange
			&& Number(state.frameIndex) === Number(before.frameIndex)
		) {
			throw new Error("The requested surface frame did not finish loading.");
		}
		return state;
	}

	function reportError(error) {
		const message = error?.message || String(error);
		elements.status.dataset.state = "error";
		elements.status.querySelector("span:last-child").textContent = message;
		appendRuntimeEvent(`ERROR · ${message}`);
	}

	function setSubmissionStatus(state, message) {
		elements.submissionStatus.dataset.state = state;
		elements.submissionStatus.querySelector("span:last-child").textContent = message;
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
			clientEventId: `event-${Date.now()}-${study.events.length + 1}`,
			event: eventName,
			unixTimeMs: Date.now(),
			runId: study.runId,
			stage: study.stage,
			condition: study.condition,
			assignedCondition: study.assignedCondition,
			assignmentMethod: study.assignmentMethod,
			stage2Order: study.stage2Order,
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

	function draftPayload(includeEvents = true) {
		const draft = {
			schemaVersion: 1,
			runId: study.runId,
			stage: study.stage,
			condition: study.condition,
			assignmentMethod: study.assignmentMethod,
			stage2Order: study.stage2Order,
			participantCode: study.participantCode,
			assignedCondition: study.assignedCondition,
			stepIndex: study.stepIndex,
			responses: study.responses,
			training: study.training,
			evidence: study.evidence,
			playback: study.playback,
			phaseDurationsMs: study.phaseDurationsMs,
			clientSavedAt: study.lastLocalSavedAt,
			remote: {
				runId: study.remote.runId,
				resumeToken: study.remote.resumeToken,
				revision: study.remote.revision,
				eventCursor: study.remote.eventCursor,
				pendingEventBatch: study.remote.pendingEventBatch,
				completed: study.remote.completed,
			},
		};
		if (includeEvents) {
			draft.events = study.events;
		}
		return draft;
	}

	function persistLocalDraft() {
		const draft = draftPayload(true);
		try {
			window.localStorage.setItem(storageKey(), JSON.stringify(draft));
		} catch (_error) {
			// The downloadable package remains available when storage is blocked.
		}
	}

	function scheduleRemoteSave(delayMs = 700) {
		study.remote.dirty = true;
		if (!study.remote.runId || study.remote.completed) {
			return;
		}
		window.clearTimeout(study.remote.saveTimer);
		study.remote.saveTimer = window.setTimeout(() => {
			syncRemote().catch(() => {});
		}, delayMs);
	}

	function saveDraft() {
		study.lastLocalSavedAt = Date.now();
		persistLocalDraft();
		scheduleRemoteSave();
	}

	function restoreDraft(draft) {
		study.runId = String(draft.runId || study.runId);
		study.condition = String(draft.condition || study.condition);
		study.assignedCondition = String(
			draft.assignedCondition || study.assignedCondition,
		);
		study.stepIndex = Math.min(
			Math.max(Number(draft.stepIndex || 0), 0),
			STEPS.length - 1,
		);
		study.responses = draft.responses || {};
		study.training = draft.training || {};
		study.evidence = Object.fromEntries(
			Object.entries(draft.evidence || {}).map(([questionId, value]) => [
				questionId,
				Array.isArray(value) ? value : value ? [value] : [],
			]),
		);
		study.playback = {
			started: Boolean(draft.playback?.started),
			maxProgress: Number(draft.playback?.maxProgress || 0),
		};
		study.events = Array.isArray(draft.events) ? draft.events : study.events;
		study.phaseDurationsMs = draft.phaseDurationsMs || {};
		study.lastLocalSavedAt = Number(draft.clientSavedAt || 0);
		study.assignmentMethod = String(
			draft.assignmentMethod || study.assignmentMethod,
		);
		study.stage2Order = draft.stage2Order || study.stage2Order;
		if (draft.remote) {
			const remote = draft.remote;
			study.remote.runId = String(remote.runId || "");
			study.remote.resumeToken = String(remote.resumeToken || "");
			study.remote.revision = Number(remote.revision || 0);
			study.remote.eventCursor = Number(remote.eventCursor || 0);
			study.remote.pendingEventBatch = remote.pendingEventBatch || null;
			study.remote.completed = Boolean(remote.completed);
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
			restoreDraft(draft);
			showToast("Saved response restored");
		} catch (_error) {
			// Ignore stale or incompatible drafts.
		}
	}

	async function apiRequest(path, options = {}) {
		const headers = { ...(options.headers || {}) };
		if (options.body !== undefined) {
			headers["Content-Type"] = "application/json";
		}
		if (study.remote.resumeToken) {
			headers["X-SandStories-Run-Token"] = study.remote.resumeToken;
		}
		const response = await fetch(`${EXPERIMENT_API}${path}`, {
			method: options.method || "GET",
			headers,
			body: options.body === undefined
				? undefined
				: JSON.stringify(options.body),
			cache: "no-store",
			keepalive: Boolean(options.keepalive),
		});
		let payload = {};
		try {
			payload = await response.json();
		} catch (_error) {
			// The status below still produces a useful failure.
		}
		if (!response.ok) {
			const error = new Error(payload.message || `Experiment service returned ${response.status}.`);
			error.status = response.status;
			error.code = payload.error || "api_error";
			throw error;
		}
		return payload;
	}

	function applyRemoteRun(remoteRun) {
		study.remote.available = true;
		study.remote.runId = remoteRun.runId;
		study.remote.revision = Number(remoteRun.revision || 0);
		study.remote.completed = remoteRun.status === "completed";
		study.assignmentMethod = remoteRun.assignmentMethod || study.assignmentMethod;
		study.stage2Order = remoteRun.stage2Order || study.stage2Order;
		study.runId = remoteRun.runId;
		study.assignedCondition = remoteRun.condition;
		if (
			study.stage === "stage2"
			|| study.stepIndex >= STEPS.findIndex((item) => item.id === "task")
		) {
			study.condition = remoteRun.condition;
		}
		for (const event of study.events) {
			event.runId = study.runId;
		}
	}

	async function resumeRemoteRun() {
		if (!study.remote.runId || !study.remote.resumeToken) {
			return false;
		}
		const remoteRun = await apiRequest(`/runs/${encodeURIComponent(study.remote.runId)}`);
		applyRemoteRun(remoteRun);
		study.remote.eventCursor = Math.min(
			Number(remoteRun.eventCount || 0),
			study.events.length,
		);
		if (
			remoteRun.draft
			&& Number(remoteRun.draft.clientSavedAt || 0) > study.lastLocalSavedAt
		) {
			const localEvents = study.events;
			restoreDraft({ ...remoteRun.draft, events: localEvents });
			applyRemoteRun(remoteRun);
		}
		persistLocalDraft();
		setSubmissionStatus(
			study.remote.completed ? "ready" : "ready",
			study.remote.completed ? "Response submitted" : "Autosave ready",
		);
		return true;
	}

	async function ensureRemoteRun() {
		if (study.remote.completed) {
			return true;
		}
		if (study.remote.runId && study.remote.resumeToken) {
			if (!study.remote.available) {
				await resumeRemoteRun();
			}
			return true;
		}
		if (!study.participantCode) {
			return false;
		}
		setSubmissionStatus("saving", "Creating run");
		const request = {
			protocolId: study.protocol.id || "sandstories_proposal_v1",
			stage: study.stage,
			participantCode: study.participantCode,
			sessionId: study.session.id || "",
			sessionUrl: study.sessionUrl,
			trainingSessionUrl: study.trainingSessionUrl,
			readyForDataCollection: study.readiness.ready,
			pilotRun: pilotMode,
		};
		if (study.fixedCondition) {
			request.conditionOverride = study.fixedCondition;
		}
		const remoteRun = await apiRequest("/runs", {
			method: "POST",
			body: request,
		});
		study.remote.resumeToken = remoteRun.resumeToken;
		applyRemoteRun(remoteRun);
		study.remote.eventCursor = 0;
		study.remote.pendingEventBatch = null;
		persistLocalDraft();
		setSubmissionStatus("ready", "Autosave ready");
		return true;
	}

	async function uploadPendingEvents(options = {}) {
		while (study.remote.eventCursor < study.events.length) {
			if (!study.remote.pendingEventBatch) {
				const start = study.remote.eventCursor;
				const end = Math.min(start + 200, study.events.length);
				study.remote.pendingEventBatch = {
					batchId: `${study.runId}:${start}:${end}`,
					start,
					end,
				};
				persistLocalDraft();
			}
			const batch = study.remote.pendingEventBatch;
			await apiRequest(`/runs/${encodeURIComponent(study.runId)}/events`, {
				method: "POST",
				body: {
					batchId: batch.batchId,
					events: study.events.slice(batch.start, batch.end),
				},
				keepalive: options.keepalive,
			});
			study.remote.eventCursor = batch.end;
			study.remote.pendingEventBatch = null;
			persistLocalDraft();
		}
	}

	async function syncRemote(options = {}) {
		if (
			study.remote.completed
			|| !study.remote.runId
			|| !study.remote.resumeToken
		) {
			return false;
		}
		if (study.remote.syncPromise) {
			study.remote.dirty = true;
			return study.remote.syncPromise;
		}
		window.clearTimeout(study.remote.saveTimer);
		study.remote.dirty = false;
		setSubmissionStatus("saving", "Saving response");
		study.remote.syncPromise = (async () => {
			await uploadPendingEvents(options);
			const remoteDraft = draftPayload(false);
			delete remoteDraft.remote;
			const result = await apiRequest(`/runs/${encodeURIComponent(study.runId)}/draft`, {
				method: "PUT",
				body: { draft: remoteDraft },
				keepalive: options.keepalive,
			});
			study.remote.revision = Number(result.revision || study.remote.revision);
			study.remote.available = true;
			study.remote.lastError = "";
			persistLocalDraft();
			setSubmissionStatus("ready", "Response saved");
			return true;
		})().catch((error) => {
			study.remote.available = false;
			study.remote.dirty = true;
			study.remote.lastError = error.message;
			persistLocalDraft();
			setSubmissionStatus("offline", "Saved locally · retrying");
			throw error;
		}).finally(() => {
			study.remote.syncPromise = null;
			if (study.remote.dirty && !study.remote.completed) {
				scheduleRemoteSave(navigator.onLine ? 1200 : 5000);
			}
		});
		return study.remote.syncPromise;
	}

	async function drainRemote() {
		for (let attempt = 0; attempt < 10; attempt += 1) {
			await syncRemote();
			if (
				!study.remote.dirty
				&& study.remote.eventCursor >= study.events.length
			) {
				return true;
			}
		}
		throw new Error("Autosave did not become idle before completion.");
	}

	async function initializeRemotePersistence() {
		try {
			await apiRequest("/health");
			study.remote.available = true;
			if (study.remote.runId && study.remote.resumeToken) {
				await resumeRemoteRun();
			} else {
				setSubmissionStatus("ready", "Storage ready");
			}
		} catch (error) {
			study.remote.available = false;
			study.remote.lastError = error.message;
			setSubmissionStatus("offline", "Local backup only");
		}
	}

	async function completeRemoteRun() {
		try {
			await ensureRemoteRun();
			await drainRemote();
			const result = await apiRequest(`/runs/${encodeURIComponent(study.runId)}/complete`, {
				method: "POST",
				body: { submission: submissionPayload() },
			});
			study.remote.completed = result.status === "completed";
			study.remote.available = true;
			persistLocalDraft();
			setSubmissionStatus("ready", "Response submitted");
			showToast("Anonymous response submitted");
			return true;
		} catch (error) {
			study.remote.lastError = error.message;
			setSubmissionStatus("offline", "Submission pending locally");
			showToast("Submission pending; local backup retained");
			return false;
		}
	}

	async function fetchJson(url) {
		const response = await fetch(url, { cache: "no-store" });
		if (!response.ok) {
			throw new Error(`${response.status} while loading ${url}`);
		}
		return response.json();
	}

	function evaluateReadiness(session, trainingMetadata) {
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
			|| session?.hand_tracks?.length
		);
		const hasObjects = Boolean(session?.objects?.length);
		const hasAudio = Boolean(sources.audio);
		const hasAnnotations = Boolean(
			session?.surface_regions?.length
			&& session?.gesture_events?.length
			&& session?.references?.length
		);
		const hasValidatedContent = Boolean(experiment.readyForDataCollection);
		const questionKey = study.stage === "stage2"
			? "stage2Questions"
			: "stage1Questions";
		const stageQuestions = Array.isArray(experiment[questionKey])
			? experiment[questionKey]
			: [];
		const hasTaskContent = Boolean(
			String(experiment.summaryPrompt || "").trim()
			&& stageQuestions.length,
		);
		const validatedQuestionIds = new Set(
			experiment.questionValidation?.validatedQuestionIds || [],
		);
		const hasQuestionValidation = Boolean(
			String(experiment.questionValidation?.rubricId || "").trim()
			&& stageQuestions.every((question) => (
				validatedQuestionIds.has(String(question?.id || ""))
			)),
		);
		const protocolMatches = Boolean(
			study.protocol?.id
			&& experiment.protocolId === study.protocol.id,
		);
		const ethicsReady = study.protocol?.ethicsApprovedForDataCollection === true;
		const trainingSources = trainingMetadata?.data_sources || {};
		const trainingHasSand = Boolean(
			trainingSources.processed_manifest
			|| trainingSources.depth_map
			|| trainingSources.detail_depth_map,
		);
		const trainingHasGestures = Boolean(
			trainingMetadata?.gesture_events?.length
			|| trainingMetadata?.mano_rgbd_full_sequence
			|| trainingMetadata?.hand_track
			|| trainingMetadata?.hand_tracks?.length,
		);
		const trainingHasAnnotations = Boolean(
			trainingMetadata?.surface_regions?.length
			&& trainingMetadata?.gesture_events?.length
			&& trainingMetadata?.references?.length,
		);
		const trainingIsSeparate = Boolean(
			study.trainingSessionUrl
			&& study.trainingSessionUrl !== study.sessionUrl,
		);
		const trainingCues = trainingMetadata?.experiment?.trainingCues || {};
		const requiredCue = study.stage === "stage2" ? "referential" : "playback";
		const hasTrainingCue = Number.isFinite(Number(trainingCues?.[requiredCue]?.start));
		const trainingReady = Boolean(
			trainingIsSeparate
			&& trainingHasSand
			&& trainingHasGestures
			&& hasTrainingCue
			&& (study.stage !== "stage2" || trainingHasAnnotations),
		);
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
			warnings.push("Creator-validated task content is not enabled.");
		}
		if (!protocolMatches) {
			warnings.push("The session does not identify the active experiment protocol.");
		}
		if (!hasTaskContent) {
			warnings.push("The session is missing its stage-specific summary prompt or questions.");
		}
		if (!hasQuestionValidation) {
			warnings.push("The creator validation record does not cover every question.");
		}
		if (!ethicsReady) {
			warnings.push("Ethics-approved participant information and consent are not enabled.");
		}
		if (!trainingIsSeparate) {
			warnings.push("A separate neutral training session is required.");
		} else if (!trainingHasSand || !trainingHasGestures) {
			warnings.push("The training session must include both the sand and hand modalities.");
		} else if (study.stage === "stage2" && !trainingHasAnnotations) {
			warnings.push("Stage 2 training needs validated referential links.");
		} else if (!hasTrainingCue) {
			warnings.push(`The training session needs a timed ${requiredCue} cue.`);
		}
		return {
			checked: true,
			ready: (
				hasSand
				&& hasGestures
				&& hasObjects
				&& hasAudio
				&& hasValidatedContent
				&& protocolMatches
				&& hasTaskContent
				&& hasQuestionValidation
				&& ethicsReady
				&& trainingReady
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
			trainingReady,
		};
	}

	function canCollectData() {
		return study.readiness.ready || pilotMode;
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
			const declaredTraining = String(
				study.session?.experiment?.trainingSession || "",
			).trim();
			if (!requestedTrainingSession && declaredTraining) {
				study.trainingSessionUrl = new URL(
					declaredTraining,
					study.sessionUrl,
				).href;
			}
			if (study.trainingSessionUrl === study.sessionUrl) {
				study.trainingSession = study.session;
			} else {
				try {
					study.trainingSession = await fetchJson(study.trainingSessionUrl);
				} catch (_error) {
					study.trainingSession = {};
				}
			}
			study.readiness = evaluateReadiness(
				study.session,
				study.trainingSession,
			);
			elements.title.textContent = researcherMode
				? (study.session.title || "Untitled sand drawing session")
				: (study.session?.experiment?.participantTitle || "Interactive sand narrative");
		} else {
			study.readiness = {
				checked: true,
				ready: false,
				warnings: ["The host could not read the session metadata."],
			};
		}
		renderStep();
	}

	async function switchViewerSession(url, metadata) {
		if (!url || study.activeSessionUrl === url) {
			return;
		}
		const previousUrl = study.activeSessionUrl;
		study.activeSessionUrl = url;
		elements.status.dataset.state = "loading";
		elements.status.querySelector("span:last-child").textContent = "Loading session";
		try {
			await sendCommand("set_playing", { playing: false }).catch(() => {});
			await sendCommand("load_session", { url }, 120000);
			elements.title.textContent = researcherMode
				? (metadata?.title || "Untitled sand drawing session")
				: (metadata?.experiment?.participantTitle || "Interactive sand narrative");
			elements.status.dataset.state = "ready";
			elements.status.querySelector("span:last-child").textContent = "Viewer ready";
			recordStudyEvent("viewer_session_switched", {
				from: previousUrl,
				to: url,
			});
		} catch (error) {
			study.activeSessionUrl = previousUrl;
			throw error;
		}
	}

	function trainingCue(name, fallbackProgress = 0.15, fallbackDuration = 2.4) {
		const cue = study.trainingSession?.experiment?.trainingCues?.[name] || {};
		const duration = Number(
			study.trainingSession?.duration
			|| study.latestGodotState?.duration
			|| 0,
		);
		const fallbackStart = Math.max(0, duration * fallbackProgress);
		return {
			start: Number.isFinite(Number(cue.start))
				? Math.max(0, Number(cue.start))
				: fallbackStart,
			duration: Number.isFinite(Number(cue.duration))
				? Math.min(Math.max(Number(cue.duration), 0.8), 12)
				: fallbackDuration,
		};
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
					assignmentMethod: study.assignmentMethod,
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
		elements.conditionChip.textContent = researcherMode
			? (training ? "Training · Full view" : meta.label)
			: (training ? "Guided practice" : "Study view");
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
			const chip = input.closest(".toggle-chip");
			if (chip) {
				chip.hidden = Boolean(
					!researcherMode
					&& (removedLayers.includes(input.dataset.layer) || unavailable),
				);
			}
		}
	}

	function updateGodotState(nextState) {
		study.latestGodotState = nextState;
		if (nextState.sessionTitle) {
			elements.title.textContent = researcherMode
				? nextState.sessionTitle
				: (study.session?.experiment?.participantTitle || "Interactive sand narrative");
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
		if (
			STEPS[study.stepIndex].id === "task"
			&& playing
			&& Number(nextState.duration || 0) > 0
		) {
			study.playback.started = true;
			study.playback.maxProgress = Math.max(
				Number(study.playback.maxProgress || 0),
				Math.min(Math.max(Number(nextState.progress || 0), 0), 1),
			);
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
		elements.next.disabled = Boolean(
			step.id === "information"
			&& study.readiness.checked
			&& !canCollectData(),
		);
		elements.next.innerHTML = study.stepIndex === STEPS.length - 2
			? "Submit responses <span aria-hidden=\"true\">→</span>"
			: "Continue <span aria-hidden=\"true\">→</span>";
	}

	function renderInformation() {
		const stageTwo = study.stage === "stage2";
		const data = study.responses.information || {};
		const readinessNotice = !study.readiness.checked
			? `
				<div class="notice">
					<strong>Checking study materials</strong>
					The task will open after the story, training session, and study protocol have been verified.
				</div>
			`
			: !study.readiness.ready
				? `
					<div class="notice warning">
						<strong>${pilotMode ? "Pilot / QA mode" : "Study materials are not ready"}</strong>
						${escapeHtml(study.readiness.warnings.join(" "))}
						${pilotMode
							? "This run is explicitly labelled as pilot data and can continue for interface testing."
							: "Data collection is blocked. A researcher can use researcher=1 or pilot=1 for a non-research QA run."}
					</div>
				`
				: "";
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
			${readinessNotice}
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
						${pilotMode ? "pilot run" : "study"}.
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

	function evidenceMarks(questionId) {
		const value = study.evidence[questionId];
		if (Array.isArray(value)) {
			return value;
		}
		return value ? [value] : [];
	}

	function renderQuestion(question, index, data) {
		const questionId = String(question.id || `question_${index + 1}`);
		const answerName = `answer:${questionId}`;
		const evidenceName = `evidence:${questionId}`;
		const answer = data[answerName] || "";
		const evidence = data[evidenceName] || "";
		const snapshots = evidenceMarks(questionId);
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
						Add current moment
					</button>
					<span class="evidence-state" data-evidence-state="${escapeHtml(questionId)}">
						${snapshots.length
							? `${snapshots.length} marked: ${snapshots.map((item) => formatTime(item.playhead)).join(", ")}`
							: "No moments marked"}
					</span>
					<button
						class="evidence-remove"
						type="button"
						data-evidence-remove="${escapeHtml(questionId)}"
						${snapshots.length ? "" : "hidden"}
					>
						Remove last
					</button>
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
		const conditionNotice = researcherMode
			? `
				<div class="notice">
					<strong>${escapeHtml(condition.label)}</strong>
					${escapeHtml(condition.description)}
				</div>
			`
			: "";
		const pilotNotice = !study.readiness.ready && pilotMode
			? `
				<div class="notice warning">
					<strong>Pilot task set — excluded from research data</strong>
					${escapeHtml(study.readiness.warnings.join(" "))}
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
			${conditionNotice}
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
		const hasValue = Object.prototype.hasOwnProperty.call(data, fieldName);
		const value = Number(hasValue ? data[fieldName] : 50);
		return `
			<div class="tlx-item">
				<label class="range-label" for="tlx-${escapeHtml(name)}">
					<span>${escapeHtml(label)}</span>
					<output data-range-output="${escapeHtml(fieldName)}">${hasValue ? value : "Not set"}</output>
				</label>
				<input
					id="tlx-${escapeHtml(name)}"
					type="range"
					${hasValue ? `name="${escapeHtml(fieldName)}"` : ""}
					data-field-name="${escapeHtml(fieldName)}"
					min="0"
					max="100"
					step="5"
					value="${value}"
				>
			</div>
		`;
	}

	function availableQuestionnaireModalities() {
		const labels = [
			["sand", "Sand surface"],
			["gestures", "Virtual hand and gestures"],
			["audio", "Narration audio"],
			["objects", "External objects"],
			["annotations", "Annotations and referential links"],
		];
		const omitted = {
			no_audio: "audio",
			no_gestures: "gestures",
			no_objects: "objects",
			no_sand: "sand",
		}[study.condition] || "";
		return labels.filter(([value]) => (
			value !== omitted
			&& (value !== "annotations" || study.stage === "stage2")
			&& study.readiness.modalities?.[value] !== false
		));
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
					${availableQuestionnaireModalities().map(([value, label]) => `
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
		const serverMessage = study.remote.completed
			? "The anonymous response has been saved by the experiment server."
			: "The response remains saved locally and will retry automatically. Download a backup before closing this page if submission is still pending.";
		const totalMs = Object.values(payload.phaseDurationsMs)
			.reduce((sum, value) => sum + Number(value || 0), 0);
		return `
			<div class="completion">
				<div class="completion-mark" aria-hidden="true">✓</div>
				<p class="task-kicker">${study.remote.completed ? "Response submitted" : "Response prepared"}</p>
				<h2>Thank you</h2>
				<p class="task-lead">
					${serverMessage}
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
						Download backup copy
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
		if (!study.readiness.checked) {
			return "Wait for the study materials to finish validation.";
		}
		if (!canCollectData()) {
			return "This story is not approved for data collection. Ask the researcher to open an explicit pilot or QA run.";
		}
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
			const minimumProgress = Math.min(Math.max(Number(
				study.session?.experiment?.minimumPlaybackProgress ?? 0.85,
			), 0.5), 1);
			if (
				!pilotMode
				&& (!study.playback.started || study.playback.maxProgress < minimumProgress)
			) {
				return `Watch the story through at least ${Math.round(minimumProgress * 100)}% before continuing.`;
			}
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
				const requiredMarks = Math.min(Math.max(Number(
					question.minEvidenceMarks || 1,
				), 1), 6);
				if (evidenceMarks(questionId).length < requiredMarks) {
					return `Mark at least ${requiredMarks} evidence moment${requiredMarks === 1 ? "" : "s"} for every answer.`;
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
			const tlxDimensions = [
				"mentalDemand",
				"physicalDemand",
				"temporalDemand",
				"performance",
				"effort",
				"frustration",
			];
			if (tlxDimensions.some((name) => !Object.prototype.hasOwnProperty.call(
				data,
				`nasa:${name}`,
			))) {
				return "Set all six NASA-TLX workload ratings.";
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
		const boundedNextIndex = Math.min(Math.max(nextIndex, 0), STEPS.length - 1);
		const targetPhase = STEPS[boundedNextIndex].id;
		if (targetPhase === "training" && !pilotMode) {
			const remoteReady = await ensureRemoteRun();
			if (!remoteReady) {
				throw new Error("The experiment server could not create this study run.");
			}
		}
		updatePhaseTiming();
		const previousPhase = STEPS[study.stepIndex].id;
		study.stepIndex = boundedNextIndex;
		study.stepStartedAt = Date.now();
		const phase = STEPS[study.stepIndex].id;
		if (previousPhase === "training" && phase !== "training") {
			await restoreTrainingVisualState();
			await switchViewerSession(study.sessionUrl, study.session);
		}
		if (phase === "training") {
			await switchViewerSession(
				study.trainingSessionUrl,
				study.trainingSession,
			);
			if (!study.remote.runId) {
				try {
					await ensureRemoteRun();
				} catch (error) {
					study.remote.lastError = error.message;
					setSubmissionStatus("offline", "Local backup only");
				}
			}
			await applyCondition(
				study.stage === "stage2" ? "stage2" : "baseline",
			);
		}
		if (phase === "task") {
			if (previousPhase === "training") {
				study.playback = { started: false, maxProgress: 0 };
			}
			if (study.remote.runId && study.assignedCondition) {
				study.condition = study.assignedCondition;
			} else {
				study.assignedCondition = deterministicCondition(study.participantCode);
				study.condition = study.assignedCondition;
				study.assignmentMethod = study.fixedCondition
					? "client_fixed_fallback"
					: "client_deterministic_fallback";
			}
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
		if (phase === "complete") {
			await completeRemoteRun();
			renderStep();
		}
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
				const cue = trainingCue("playback", 0.15, 2.4);
				recordStudyEvent("training_cue_started", {
					cue: "playback",
					...cue,
				});
				await seekAndWait(cue.start);
				await sendCommand("set_playing", { playing: true });
				await waitFor(cue.duration * 1000);
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
				const cue = trainingCue("referential", 0.7, 1.8);
				recordStudyEvent("training_cue_started", {
					cue: "referential",
					...cue,
				});
				await sendCommand("set_layer", {
					layer: "annotations",
					visible: true,
				});
				await sendCommand("set_layer", {
					layer: "gestures",
					visible: true,
				});
				await seekAndWait(cue.start);
				await sendCommand("set_playing", { playing: true });
				await waitFor(cue.duration * 1000);
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
		const snapshots = evidenceMarks(questionId);
		snapshots.push(snapshot);
		study.evidence[questionId] = snapshots.slice(-6);
		const label = elements.taskContent.querySelector(
			`[data-evidence-state="${CSS.escape(questionId)}"]`,
		);
		if (label) {
			label.textContent = (
				`${study.evidence[questionId].length} marked: `
				+ study.evidence[questionId]
					.map((item) => formatTime(item.playhead))
					.join(", ")
			);
		}
		const removeButton = elements.taskContent.querySelector(
			`[data-evidence-remove="${CSS.escape(questionId)}"]`,
		);
		if (removeButton) {
			removeButton.hidden = false;
		}
		saveDraft();
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

	function removeLastEvidence(questionId) {
		const snapshots = evidenceMarks(questionId);
		const removed = snapshots.pop();
		study.evidence[questionId] = snapshots;
		saveDraft();
		recordStudyEvent("task_evidence_removed", {
			questionId,
			capturedUnixTimeMs: removed?.capturedUnixTimeMs || null,
		});
		renderStep();
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
		for (const button of elements.taskContent.querySelectorAll(
			"[data-evidence-remove]",
		)) {
			button.addEventListener("click", () => {
				collectCurrentForm();
				removeLastEvidence(button.dataset.evidenceRemove);
			});
		}
		for (const input of elements.taskContent.querySelectorAll(
			"input[type=\"range\"]",
		)) {
			input.addEventListener("input", () => {
				const fieldName = input.name || input.dataset.fieldName;
				if (fieldName && !input.name) {
					input.name = fieldName;
				}
				const output = elements.taskContent.querySelector(
					`[data-range-output="${CSS.escape(fieldName || "")}"]`,
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
			if (input.type !== "range") {
				input.addEventListener("input", collectCurrentForm);
			}
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
				viewSnapshot: evidenceMarks(questionId).at(-1) || {},
				viewSnapshots: evidenceMarks(questionId),
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
			payload.nasaTlxRaw[key] = Object.prototype.hasOwnProperty.call(
				data,
				`nasa:${key}`,
			)
				? Number(data[`nasa:${key}`])
				: null;
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
			assignmentMethod: study.assignmentMethod,
			stage2Order: study.stage2Order,
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
		window.clearTimeout(study.remote.saveTimer);
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
			study.activeSessionUrl = url;
			study.session = session;
			const declaredTraining = String(
				requestedTrainingSession || session?.experiment?.trainingSession || "",
			).trim();
			study.trainingSessionUrl = declaredTraining
				? new URL(declaredTraining, url).href
				: url;
			study.trainingSession = study.trainingSessionUrl === url
				? session
				: await fetchJson(study.trainingSessionUrl).catch(() => ({}));
			study.readiness = evaluateReadiness(session, study.trainingSession);
			elements.title.textContent = researcherMode
				? (session.title || "Untitled sand drawing session")
				: (session?.experiment?.participantTitle || "Interactive sand narrative");
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
		elements.back.addEventListener("click", async () => {
			if (navigationBusy) {
				return;
			}
			navigationBusy = true;
			collectCurrentForm();
			try {
				await moveToStep(study.stepIndex - 1);
			} catch (error) {
				reportError(error);
			} finally {
				navigationBusy = false;
			}
		});
		elements.next.addEventListener("click", async () => {
			if (navigationBusy) {
				return;
			}
			const validation = validateCurrentStep();
			if (validation) {
				elements.validation.textContent = validation;
				return;
			}
			elements.validation.textContent = "";
			recordStudyEvent("phase_completed", {
				phase: STEPS[study.stepIndex].id,
			});
			navigationBusy = true;
			try {
				await moveToStep(study.stepIndex + 1);
			} catch (error) {
				reportError(error);
			} finally {
				navigationBusy = false;
			}
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
		elements.timeline.addEventListener("change", async () => {
			timelineDragging = false;
			const progress = Number(elements.timeline.value) / 1000;
			const duration = Number(study.latestGodotState?.duration || 0);
			const resumePlayback = Boolean(study.latestGodotState?.playing);
			try {
				if (resumePlayback) {
					await sendCommand("set_playing", { playing: false });
				}
				await seekAndWait(progress * duration);
				if (resumePlayback) {
					await sendCommand("set_playing", { playing: true });
				}
					if (STEPS[study.stepIndex].id === "training") {
						const playback = trainingItems().find(
							(item) => item.id === "playback",
						);
						if (playback) {
							setTrainingComplete(playback.id);
						}
					}
					recordStudyEvent("timeline_seek", {
						progress,
					});
			} catch (error) {
				reportError(error);
			}
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
		window.addEventListener("online", () => {
			if (study.remote.runId && !study.remote.completed) {
				syncRemote().catch(() => {});
			} else {
				initializeRemotePersistence().catch(() => {});
			}
		});
		window.addEventListener("offline", () => {
			setSubmissionStatus("offline", "Saved locally · offline");
		});
		window.addEventListener("pagehide", () => {
			if (study.remote.runId && !study.remote.completed) {
				syncRemote({ keepalive: true }).catch(() => {});
			}
		});
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
				sessionUrl: study.activeSessionUrl,
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
		await Promise.all([
			loadStudyMetadata(),
			initializeRemotePersistence(),
		]);
	}

	start().catch(reportError);
}());
