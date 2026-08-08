import { access, readFile, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { STAGE_ONE_CONDITIONS } from "./experiment_api.mjs";

const ASSET_FIELDS = [
	"processed_manifest",
	"depth_map",
	"detail_depth_map",
	"surface_mask",
	"texture_map",
	"audio",
];

function checkCollector() {
	const checks = [];
	return {
		add(id, ok, message, severity = "error", details = undefined) {
			checks.push({ id, ok: Boolean(ok), severity, message, ...(details ? { details } : {}) });
		},
		checks,
	};
}

function nonEmptyArray(value) {
	return Array.isArray(value) && value.length > 0;
}

function modalityState(session) {
	const sources = session?.data_sources || {};
	return {
		sand: Boolean(
			sources.processed_manifest
			|| sources.depth_map
			|| sources.detail_depth_map
			|| nonEmptyArray(session?.surface_heights)
		),
		gestures: Boolean(
			nonEmptyArray(session?.gesture_events)
			|| session?.mano_rgbd_full_sequence
			|| session?.hand_track
			|| nonEmptyArray(session?.hand_tracks)
		),
		objects: nonEmptyArray(session?.objects),
		audio: Boolean(sources.audio),
		annotations: Boolean(
			nonEmptyArray(session?.surface_regions)
			&& nonEmptyArray(session?.gesture_events)
			&& nonEmptyArray(session?.references)
		),
	};
}

function resolveAssetPath(assetPath, sessionPath, projectRoot) {
	if (!assetPath || /^https?:\/\//iu.test(assetPath)) {
		return null;
	}
	if (assetPath.startsWith("res://")) {
		return resolve(projectRoot, assetPath.slice("res://".length));
	}
	if (isAbsolute(assetPath)) {
		return resolve(assetPath);
	}
	return resolve(dirname(sessionPath), assetPath);
}

async function pathExists(path) {
	try {
		await access(path);
		return true;
	} catch {
		return false;
	}
}

function validateQuestions(collector, questions, stage) {
	collector.add(
		`${stage}.questions_present`,
		nonEmptyArray(questions),
		`${stage} must have at least one comprehension question.`,
	);
	if (!Array.isArray(questions)) {
		return;
	}
	const ids = new Set();
	for (const [index, question] of questions.entries()) {
		const prefix = `${stage}.question.${index + 1}`;
		const id = String(question?.id || "").trim();
		collector.add(`${prefix}.id`, Boolean(id) && !ids.has(id), `${prefix} has a unique non-empty id.`);
		ids.add(id);
		collector.add(`${prefix}.prompt`, Boolean(String(question?.prompt || "").trim()), `${prefix} has a prompt.`);
		collector.add(
			`${prefix}.evidence_prompt`,
			Boolean(String(question?.evidencePrompt || "").trim()),
			`${prefix} asks the participant to explain evidence.`,
		);
		collector.add(
			`${prefix}.type`,
			["choice", "short"].includes(question?.type),
			`${prefix} uses a supported response type.`,
		);
		if (question?.type === "choice") {
			collector.add(
				`${prefix}.options`,
				Array.isArray(question.options)
					&& question.options.length >= 2
					&& question.options.every((option) => String(option).trim()),
				`${prefix} has at least two non-empty options.`,
			);
		}
	}
}

function validateTemporalEntries(collector, entries, label, duration) {
	if (!Array.isArray(entries)) {
		return;
	}
	for (const [index, entry] of entries.entries()) {
		const start = Number(entry?.start ?? 0);
		const end = Number(entry?.end ?? duration);
		collector.add(
			`timeline.${label}.${index + 1}`,
			Number.isFinite(start)
				&& Number.isFinite(end)
				&& start >= 0
				&& end >= start
				&& end <= duration + 0.05,
			`${label} item ${index + 1} lies within the session timeline.`,
		);
	}
}

async function validateManifest(collector, manifestPath, sessionPath) {
	let manifest;
	try {
		manifest = JSON.parse(await readFile(manifestPath, "utf8"));
	} catch (error) {
		collector.add("manifest.json", false, `Processed manifest is not readable JSON: ${error.message}`);
		return;
	}
	const frames = manifest.frames;
	collector.add("manifest.frames", nonEmptyArray(frames), "Processed manifest contains frames.");
	if (!Array.isArray(frames)) {
		return;
	}
	collector.add(
		"manifest.frame_count",
		!Number.isFinite(Number(manifest.processedFrameCount))
			|| Number(manifest.processedFrameCount) === frames.length,
		"processedFrameCount matches the manifest frame array.",
		"error",
		{ declared: manifest.processedFrameCount, actual: frames.length },
	);
	let previousTime = -Infinity;
	let timelineValid = true;
	const missing = [];
	for (const [index, frame] of frames.entries()) {
		const time = Number(frame?.time);
		if (!Number.isFinite(time) || time < previousTime) {
			timelineValid = false;
		}
		previousTime = time;
		for (const field of ["cleanDepth", "cleanRgb", "virtualHandMesh"]) {
			const reference = String(frame?.[field] || "");
			if (!reference) {
				continue;
			}
			const assetPath = resolve(dirname(sessionPath), reference);
			if (!await pathExists(assetPath) && missing.length < 25) {
				missing.push({ frame: index, field, reference });
			}
		}
	}
	collector.add("manifest.timeline", timelineValid, "Manifest frame times are finite and monotonic.");
	collector.add(
		"manifest.frame_assets",
		missing.length === 0,
		missing.length
			? `${missing.length} sampled frame assets are missing (report capped at 25).`
			: "All referenced clean RGB, clean depth, and virtual-hand frame assets exist.",
		"error",
		missing.length ? { missing } : undefined,
	);
}

export async function preflightExperiment({
	session,
	sessionPath,
	protocol,
	projectRoot,
	trainingSession = undefined,
	trainingSessionPath = "",
}) {
	const collector = checkCollector();
	const duration = Number(session?.duration);
	const declaredTraining = String(session?.experiment?.trainingSession || "").trim();
	let resolvedTrainingPath = trainingSessionPath
		? resolve(trainingSessionPath)
		: resolveAssetPath(declaredTraining, sessionPath, projectRoot);
	let resolvedTraining = trainingSession;
	if (!resolvedTraining && resolvedTrainingPath && await pathExists(resolvedTrainingPath)) {
		try {
			resolvedTraining = JSON.parse(await readFile(resolvedTrainingPath, "utf8"));
		} catch (error) {
			collector.add("training.json", false, `Training session is not readable JSON: ${error.message}`);
		}
	}
	collector.add("session.id", Boolean(String(session?.id || "").trim()), "Session has an id.");
	collector.add("session.title", Boolean(String(session?.title || "").trim()), "Session has a title.");
	collector.add(
		"session.participant_title",
		Boolean(String(session?.experiment?.participantTitle || "").trim()),
		"Session has a neutral participant-facing title.",
	);
	collector.add("session.duration", Number.isFinite(duration) && duration > 0, "Session duration is positive and finite.");
	collector.add(
		"protocol.id",
		Boolean(protocol?.id) && session?.experiment?.protocolId === protocol.id,
		`Session experiment.protocolId must equal ${protocol?.id || "the active protocol"}.`,
	);
	collector.add(
		"protocol.stage1_conditions",
		Array.isArray(protocol?.stage1?.conditions)
			&& protocol.stage1.conditions.length === STAGE_ONE_CONDITIONS.length
			&& STAGE_ONE_CONDITIONS.every((condition) => protocol.stage1.conditions.includes(condition)),
		"Protocol defines exactly the five Stage 1 conditions.",
	);
	collector.add(
		"protocol.ethics_ready",
		protocol?.ethicsApprovedForDataCollection === true,
		"Protocol must explicitly enable ethics-approved participant information and consent before data collection.",
	);

	const modalities = modalityState(session);
	for (const [modality, available] of Object.entries(modalities)) {
		collector.add(
			`modality.${modality}`,
			available,
			available
				? `${modality} modality is present.`
				: `Required ${modality} modality is missing${modality === "annotations" ? "; Stage 2 needs surface regions, gesture events, and references" : ""}.`,
			"error",
		);
	}
	collector.add(
		"experiment.ready",
		session?.experiment?.readyForDataCollection === true,
		"experiment.readyForDataCollection must be explicitly true.",
	);
	collector.add(
		"experiment.summary_prompt",
		Boolean(String(session?.experiment?.summaryPrompt || "").trim()),
		"Experiment metadata must contain a non-empty summary prompt.",
	);
	collector.add(
		"experiment.playback_requirement",
		Number(session?.experiment?.minimumPlaybackProgress) >= 0.5
			&& Number(session?.experiment?.minimumPlaybackProgress) <= 1,
		"Experiment metadata defines minimumPlaybackProgress between 0.5 and 1.",
	);
	validateQuestions(collector, session?.experiment?.stage1Questions, "stage1");
	validateQuestions(collector, session?.experiment?.stage2Questions, "stage2");
	const allQuestions = [
		...(session?.experiment?.stage1Questions || []),
		...(session?.experiment?.stage2Questions || []),
	];
	const validation = session?.experiment?.questionValidation;
	const validatedQuestionIds = new Set(validation?.validatedQuestionIds || []);
	collector.add(
		"experiment.question_validation",
		Boolean(String(validation?.rubricId || "").trim())
			&& allQuestions.length > 0
			&& allQuestions.every((question) => (
				validatedQuestionIds.has(String(question?.id || ""))
			)),
		"Creator validation receipt covers every comprehension question without exposing expected answers.",
	);

	collector.add(
		"training.separate_session",
		Boolean(declaredTraining)
			&& Boolean(resolvedTrainingPath)
			&& resolve(resolvedTrainingPath) !== resolve(sessionPath),
		"A distinct neutral training session is declared.",
	);
	collector.add(
		"training.session_readable",
		Boolean(resolvedTraining),
		"The declared training session can be read.",
	);
	if (resolvedTraining) {
		const trainingModalities = modalityState(resolvedTraining);
		collector.add("training.sand", trainingModalities.sand, "Training includes the sand modality.");
		collector.add("training.gestures", trainingModalities.gestures, "Training includes the hand/gesture modality.");
		collector.add("training.annotations", trainingModalities.annotations, "Training includes validated relations for Stage 2 practice.");
		for (const cueName of ["playback", "referential"]) {
			const cue = resolvedTraining?.experiment?.trainingCues?.[cueName];
			collector.add(
				`training.cue.${cueName}`,
				Number.isFinite(Number(cue?.start))
					&& Number(cue.start) >= 0
					&& Number(cue.start) <= Number(resolvedTraining.duration || 0),
				`Training has a creator-checked ${cueName} cue inside its timeline.`,
			);
		}
	}

	for (const condition of STAGE_ONE_CONDITIONS) {
		const omitted = {
			baseline: null,
			no_audio: "audio",
			no_gestures: "gestures",
			no_objects: "objects",
			no_sand: "sand",
		}[condition];
		const required = ["sand", "gestures", "objects", "audio"];
		collector.add(
			`condition.${condition}.contrast_source`,
			required.every((modality) => modalities[modality]),
			`${condition} requires a source session containing sand, gestures, objects, and audio before ${omitted ? `omitting ${omitted}` : "showing the baseline"}.`,
		);
	}

	if (Number.isFinite(duration) && duration > 0) {
		validateTemporalEntries(collector, session?.gesture_events, "gesture", duration);
		validateTemporalEntries(collector, session?.surface_regions, "surface_region", duration);
		validateTemporalEntries(collector, session?.references, "reference", duration);
		validateTemporalEntries(collector, session?.annotations, "annotation", duration);
	}

	const knownIds = new Set();
	for (const collection of [
		session?.objects,
		session?.surface_regions,
		session?.gesture_events,
		session?.annotations,
		session?.hand_tracks,
	]) {
		for (const item of collection || []) {
			if (item?.id) {
				knownIds.add(String(item.id));
			}
		}
	}
	for (const [index, reference] of (session?.references || []).entries()) {
		collector.add(
			`reference.${index + 1}.source`,
			knownIds.has(String(reference?.source || "")),
			`Reference ${index + 1} source resolves to a known session entity.`,
		);
		collector.add(
			`reference.${index + 1}.target`,
			knownIds.has(String(reference?.target || "")),
			`Reference ${index + 1} target resolves to a known session entity.`,
		);
	}

	const sources = session?.data_sources || {};
	let manifestPath = null;
	for (const field of ASSET_FIELDS) {
		const value = String(sources[field] || "");
		if (!value) {
			continue;
		}
		const localPath = resolveAssetPath(value, sessionPath, projectRoot);
		if (!localPath) {
			collector.add(
				`asset.${field}`,
				false,
				`${field} is remote and must be verified by runtime preflight: ${value}`,
				"warning",
			);
			continue;
		}
		const exists = await pathExists(localPath);
		collector.add(
			`asset.${field}`,
			exists,
			exists ? `${field} resolves to ${localPath}.` : `${field} is missing at ${localPath}.`,
		);
		if (field === "processed_manifest" && exists) {
			manifestPath = localPath;
		}
	}
	if (manifestPath) {
		await validateManifest(collector, manifestPath, sessionPath);
	}

	const failures = collector.checks.filter((check) => !check.ok && check.severity === "error");
	const warnings = collector.checks.filter((check) => !check.ok && check.severity === "warning");
	return {
		schemaVersion: 1,
		ok: failures.length === 0,
		sessionId: session?.id || "",
		protocolId: protocol?.id || "",
		modalities,
		summary: {
			passed: collector.checks.filter((check) => check.ok).length,
			failed: failures.length,
			warnings: warnings.length,
		},
		checks: collector.checks,
	};
}

function parseArguments(argv) {
	const options = {};
	for (let index = 0; index < argv.length; index += 1) {
		const key = argv[index];
		if (!["--session", "--training-session", "--protocol", "--project-root", "--report"].includes(key)) {
			throw new Error(`Unknown argument: ${key}`);
		}
		options[key.slice(2)] = argv[index + 1];
		index += 1;
	}
	if (!options.session || !options.protocol) {
		throw new Error("Usage: node experiment_preflight.mjs --session <session.json> --protocol <experiment_protocol.json> [--training-session <session.json>] [--project-root <Godot>] [--report <report.json>]");
	}
	return options;
}

async function runCli() {
	const options = parseArguments(process.argv.slice(2));
	const sessionPath = resolve(options.session);
	const protocolPath = resolve(options.protocol);
	const projectRoot = resolve(options["project-root"] || dirname(protocolPath));
	const report = await preflightExperiment({
		session: JSON.parse(await readFile(sessionPath, "utf8")),
		sessionPath,
		protocol: JSON.parse(await readFile(protocolPath, "utf8")),
		projectRoot,
		trainingSession: options["training-session"]
			? JSON.parse(await readFile(resolve(options["training-session"]), "utf8"))
			: undefined,
		trainingSessionPath: options["training-session"]
			? resolve(options["training-session"])
			: "",
	});
	if (options.report) {
		await writeFile(resolve(options.report), `${JSON.stringify(report, null, 2)}\n`, "utf8");
	}
	console.log(
		`${report.ok ? "PASS" : "FAIL"} ${report.sessionId}: `
		+ `${report.summary.passed} passed, ${report.summary.failed} failed, `
		+ `${report.summary.warnings} warnings`,
	);
	for (const check of report.checks.filter((item) => !item.ok)) {
		console.log(`${check.severity.toUpperCase()} ${check.id}: ${check.message}`);
	}
	process.exitCode = report.ok ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	runCli().catch((error) => {
		console.error(error?.stack || error);
		process.exitCode = 2;
	});
}
