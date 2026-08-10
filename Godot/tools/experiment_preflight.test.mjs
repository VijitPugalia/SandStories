import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { preflightExperiment } from "./experiment_preflight.mjs";

const protocolPath = fileURLToPath(
	new URL("../data/experiment_protocol.json", import.meta.url),
);
const protocol = JSON.parse(await readFile(protocolPath, "utf8"));
const readyProtocol = {
	...protocol,
	ethicsApprovedForDataCollection: true,
};

function question(id) {
	return {
		id,
		type: "choice",
		prompt: "Which relation is shown?",
		options: ["A", "B"],
		evidencePrompt: "Describe the evidence.",
	};
}

async function makeFixture() {
	const root = await mkdtemp(join(tmpdir(), "sandstories-preflight-"));
	for (const name of [
		"depth-0.png",
		"rgb-0.png",
		"hand-0.meshbin.gz",
		"surface-mask.png",
		"narration.ogg",
	]) {
		await writeFile(join(root, name), "fixture", "utf8");
	}
	const manifest = {
		processedFrameCount: 1,
		frames: [{
			frameIndex: 0,
			time: 0,
			cleanDepth: "depth-0.png",
			cleanRgb: "rgb-0.png",
			virtualHandMesh: "hand-0.meshbin.gz",
		}],
	};
	await writeFile(
		join(root, "processed_manifest.json"),
		JSON.stringify(manifest),
		"utf8",
	);
	const sessionPath = join(root, "session.json");
	const session = {
		id: "fixture-session",
		title: "Fixture",
		duration: 4,
		data_sources: {
			processed_manifest: "processed_manifest.json",
			depth_map: "depth-0.png",
			texture_map: "rgb-0.png",
			surface_mask: "surface-mask.png",
			audio: "narration.ogg",
		},
		mano_rgbd_full_sequence: { meshFrameCount: 1 },
		objects: [{ id: "object-1" }],
		hand_tracks: [{ id: "hand-1" }],
		gesture_events: [{ id: "gesture-1", start: 0, end: 2 }],
		surface_regions: [{ id: "region-1", start: 0, end: 3 }],
		annotations: [{ id: "annotation-1", start: 0, end: 3 }],
		references: [{
			id: "reference-1",
			source: "hand-1",
			target: "region-1",
			start: 0,
			end: 2,
		}],
		experiment: {
			protocolId: protocol.id,
			participantTitle: "Practice sand narrative",
			readyForDataCollection: true,
			trainingSession: "training_session.json",
			minimumPlaybackProgress: 0.85,
			summaryPrompt: "Summarise the story.",
			stage1Questions: [question("stage1-question")],
			stage2Questions: [question("stage2-question")],
			questionValidation: {
				rubricId: "fixture-rubric-v1",
				validatedQuestionIds: [
					"stage1-question",
					"stage2-question",
				],
			},
		},
	};
	const trainingSession = structuredClone(session);
	trainingSession.id = "fixture-training-session";
	trainingSession.title = "Neutral training";
	trainingSession.experiment = {
		participantTitle: "Viewer practice",
		trainingCues: {
			playback: { start: 0.5, duration: 1.5 },
			referential: { start: 1, duration: 1.5 },
		},
	};
	await writeFile(
		join(root, "training_session.json"),
		JSON.stringify(trainingSession),
		"utf8",
	);
	await writeFile(sessionPath, JSON.stringify(session), "utf8");
	return { root, session, sessionPath };
}

test("a complete existing-session contract passes preflight", async () => {
	const fixture = await makeFixture();
	try {
		const report = await preflightExperiment({
			session: fixture.session,
			sessionPath: fixture.sessionPath,
			protocol: readyProtocol,
			projectRoot: fixture.root,
		});
		assert.equal(report.ok, true);
		assert.equal(report.summary.failed, 0);
		assert.equal(report.modalities.audio, true);
		assert.ok(report.summary.passed > 20);
	} finally {
		await rm(fixture.root, { recursive: true, force: true });
	}
});

test("preflight reports missing contrast modalities and assets", async () => {
	const fixture = await makeFixture();
	try {
		fixture.session.data_sources.audio = "missing.ogg";
		fixture.session.objects = [];
		const report = await preflightExperiment({
			session: fixture.session,
			sessionPath: fixture.sessionPath,
			protocol: readyProtocol,
			projectRoot: fixture.root,
		});
		assert.equal(report.ok, false);
		const failedIds = new Set(
			report.checks.filter((check) => !check.ok).map((check) => check.id),
		);
		assert.ok(failedIds.has("modality.objects"));
		assert.ok(failedIds.has("asset.audio"));
		assert.ok(failedIds.has("condition.no_objects.contrast_source"));
	} finally {
		await rm(fixture.root, { recursive: true, force: true });
	}
});
