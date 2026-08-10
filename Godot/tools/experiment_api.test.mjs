import assert from "node:assert/strict";
import http from "node:http";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import {
	ApiError,
	createExperimentApi,
	ExperimentStore,
	STAGE_ONE_CONDITIONS,
} from "./experiment_api.mjs";

const protocolPath = resolve(
	new URL("../data/experiment_protocol.json", import.meta.url).pathname.slice(1),
);

async function withStore(callback, options = {}) {
	const dataRoot = await mkdtemp(join(tmpdir(), "sandstories-api-test-"));
	try {
		const store = await new ExperimentStore({
			dataRoot,
			protocolPath,
			allowConditionOverride: options.allowConditionOverride || false,
		}).init();
		await callback(store, dataRoot);
	} finally {
		await rm(dataRoot, { recursive: true, force: true });
	}
}

function createInput(suffix, extra = {}) {
	return {
		protocolId: "sandstories_proposal_v1",
		stage: "stage1",
		participantCode: `qa-${suffix}`,
		sessionId: "test-session",
		sessionUrl: "http://localhost/session.json",
		trainingSessionUrl: "http://localhost/training/session.json",
		readyForDataCollection: true,
		...extra,
	};
}

test("Stage 1 assignment is balanced in randomized blocks", async () => {
	await withStore(async (store) => {
		const counts = Object.fromEntries(
			STAGE_ONE_CONDITIONS.map((condition) => [condition, 0]),
		);
		for (let index = 0; index < 15; index += 1) {
			const run = await store.createRun(createInput(index));
			counts[run.condition] += 1;
			assert.equal(run.assignmentMethod, "server_balanced_block");
			assert.ok(run.resumeToken.length > 30);
		}
		assert.deepEqual(Object.values(counts).sort(), [3, 3, 3, 3, 3]);
	});
});

test("Stage 2 relation order is balanced in randomized blocks", async () => {
	await withStore(async (store) => {
		const counts = new Map();
		for (let index = 0; index < 6; index += 1) {
			const run = await store.createRun(createInput(`stage2-${index}`, {
				stage: "stage2",
			}));
			assert.equal(run.assignmentMethod, "server_stage2_balanced_order");
			assert.deepEqual(
				[...run.stage2Order.sequence].sort(),
				["relations_hidden", "relations_visible"],
			);
			counts.set(run.stage2Order.id, (counts.get(run.stage2Order.id) || 0) + 1);
		}
		assert.deepEqual([...counts.values()].sort(), [3, 3]);
	});
});

test("run tokens protect resume and writes", async () => {
	await withStore(async (store) => {
		const run = await store.createRun(createInput("auth"));
		await assert.rejects(
			store.resumeRun(run.runId, "wrong-token"),
			(error) => error instanceof ApiError && error.status === 401,
		);
		const resumed = await store.resumeRun(run.runId, run.resumeToken);
		assert.equal(resumed.runId, run.runId);
		assert.deepEqual(resumed.draft, {});
	});
});

test("drafts, idempotent event batches, and completion persist", async () => {
	await withStore(async (store, dataRoot) => {
		const run = await store.createRun(createInput("lifecycle"));
		const saved = await store.saveDraft(run.runId, run.resumeToken, {
			stepIndex: 3,
			responses: { task: { summary: "draft" } },
		});
		assert.equal(saved.revision, 1);

		const firstBatch = await store.appendEvents(
			run.runId,
			run.resumeToken,
			"batch-1",
			[{ event: "one" }, { event: "two" }],
		);
		const repeatedBatch = await store.appendEvents(
			run.runId,
			run.resumeToken,
			"batch-1",
			[{ event: "one" }, { event: "two" }],
		);
		assert.deepEqual(firstBatch, { duplicate: false, eventCount: 2 });
		assert.deepEqual(repeatedBatch, { duplicate: true, eventCount: 2 });

		const submission = {
			runId: run.runId,
			stage: run.stage,
			condition: run.condition,
			readyForDataCollection: true,
			responses: { summary: "complete" },
		};
		const completed = await store.completeRun(
			run.runId,
			run.resumeToken,
			submission,
		);
		assert.equal(completed.status, "completed");
		const completionFile = JSON.parse(await readFile(
			join(dataRoot, "runs", run.runId, "submission.json"),
			"utf8",
		));
		assert.deepEqual(completionFile.submission, submission);
		await assert.rejects(
			store.saveDraft(run.runId, run.resumeToken, { changed: true }),
			(error) => error instanceof ApiError && error.status === 409,
		);
	});
});

test("condition overrides are explicit QA-only behavior", async () => {
	await withStore(async (store) => {
		await assert.rejects(
			store.createRun(createInput("override", {
				conditionOverride: "no_audio",
			})),
			(error) => error instanceof ApiError && error.status === 403,
		);
	});
	await withStore(async (store) => {
		const run = await store.createRun(createInput("override-enabled", {
			conditionOverride: "no_audio",
		}));
		assert.equal(run.condition, "no_audio");
		assert.equal(run.assignmentMethod, "server_fixed_qa");
	}, { allowConditionOverride: true });
});

test("unready sessions require an explicitly enabled pilot run", async () => {
	await withStore(async (store) => {
		await assert.rejects(
			store.createRun(createInput("not-ready", {
				readyForDataCollection: false,
			})),
			(error) => error instanceof ApiError && error.code === "session_not_ready",
		);
	});
	await withStore(async (store) => {
		const run = await store.createRun(createInput("pilot", {
			readyForDataCollection: false,
			pilotRun: true,
		}));
		assert.equal(run.pilotRun, true);
		const completed = await store.completeRun(run.runId, run.resumeToken, {
			runId: run.runId,
			stage: run.stage,
			condition: run.condition,
			readyForDataCollection: false,
		});
		assert.equal(completed.status, "completed");
	}, { allowConditionOverride: true });
});

test("HTTP API exposes create, autosave, resume, events, and completion", async () => {
	await withStore(async (store) => {
		const handler = createExperimentApi(store);
		const server = http.createServer(async (request, response) => {
			const url = new URL(request.url, "http://127.0.0.1");
			if (!await handler(request, response, url)) {
				response.writeHead(404);
				response.end();
			}
		});
		await new Promise((resolvePromise) => server.listen(0, "127.0.0.1", resolvePromise));
		try {
			const address = server.address();
			const base = `http://127.0.0.1:${address.port}/api/experiment`;
			const health = await fetch(`${base}/health`).then((response) => response.json());
			assert.equal(health.ok, true);

			const createResponse = await fetch(`${base}/runs`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(createInput("http")),
			});
			assert.equal(createResponse.status, 201);
			const run = await createResponse.json();
			const headers = {
				"Content-Type": "application/json",
				"X-SandStories-Run-Token": run.resumeToken,
			};
			const draftResponse = await fetch(`${base}/runs/${run.runId}/draft`, {
				method: "PUT",
				headers,
				body: JSON.stringify({ draft: { stepIndex: 2 } }),
			});
			assert.equal(draftResponse.status, 200);
			const eventResponse = await fetch(`${base}/runs/${run.runId}/events`, {
				method: "POST",
				headers,
				body: JSON.stringify({ batchId: "http-batch", events: [{ event: "saved" }] }),
			});
			assert.equal(eventResponse.status, 200);
			const resumed = await fetch(`${base}/runs/${run.runId}`, { headers })
				.then((response) => response.json());
			assert.equal(resumed.draft.stepIndex, 2);
			assert.equal(resumed.eventCount, 1);
			const completion = await fetch(`${base}/runs/${run.runId}/complete`, {
				method: "POST",
				headers,
				body: JSON.stringify({
						submission: {
						runId: run.runId,
						stage: run.stage,
							condition: run.condition,
							readyForDataCollection: true,
					},
				}),
			}).then((response) => response.json());
			assert.equal(completion.status, "completed");
		} finally {
			await new Promise((resolvePromise, reject) => server.close((error) => {
				if (error) reject(error); else resolvePromise();
			}));
		}
	});
});
