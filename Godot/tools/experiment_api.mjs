import { createHash, randomBytes, randomInt, randomUUID } from "node:crypto";
import {
	appendFile,
	mkdir,
	readFile,
	rename,
	writeFile,
} from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

export const STAGE_ONE_CONDITIONS = Object.freeze([
	"baseline",
	"no_audio",
	"no_gestures",
	"no_objects",
	"no_sand",
]);

const VALID_STAGES = new Set(["stage1", "stage2"]);
const RUN_ID_PATTERN = /^ss-[a-z0-9-]{12,80}$/;
const BATCH_ID_PATTERN = /^[a-zA-Z0-9._:-]{1,160}$/;
const MAX_BODY_BYTES = 8 * 1024 * 1024;

function isoNow() {
	return new Date().toISOString();
}

function tokenHash(token) {
	return createHash("sha256").update(String(token)).digest("hex");
}

function publicRun(record, includeDraft = false) {
	const result = {
		schemaVersion: record.schemaVersion,
		runId: record.runId,
		protocolId: record.protocolId,
		stage: record.stage,
		condition: record.condition,
		assignmentMethod: record.assignmentMethod,
		status: record.status,
		revision: record.revision,
		eventCount: record.eventCount,
		createdAt: record.createdAt,
		updatedAt: record.updatedAt,
		completedAt: record.completedAt || null,
		sessionId: record.sessionId || "",
		sessionUrl: record.sessionUrl || "",
		trainingSessionUrl: record.trainingSessionUrl || "",
		readyForDataCollection: Boolean(record.readyForDataCollection),
		pilotRun: Boolean(record.pilotRun),
		stage2Order: record.stage2Order || null,
	};
	if (includeDraft) {
		result.draft = record.draft || {};
	}
	return result;
}

function sanitizeString(value, maximumLength = 512) {
	const text = String(value ?? "").trim();
	if (text.length > maximumLength || /[\u0000-\u001f\u007f]/u.test(text)) {
		throw new ApiError(400, "invalid_text", "A text field is invalid or too long.");
	}
	return text;
}

function shuffle(values) {
	const result = [...values];
	for (let index = result.length - 1; index > 0; index -= 1) {
		const swapIndex = randomInt(index + 1);
		[result[index], result[swapIndex]] = [result[swapIndex], result[index]];
	}
	return result;
}

async function readJson(path, fallback = undefined) {
	try {
		return JSON.parse(await readFile(path, "utf8"));
	} catch (error) {
		if (error?.code === "ENOENT" && fallback !== undefined) {
			return fallback;
		}
		throw error;
	}
}

async function writeJsonAtomic(path, value) {
	await mkdir(dirname(path), { recursive: true });
	const temporary = `${path}.${process.pid}.${randomBytes(6).toString("hex")}.tmp`;
	await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, {
		encoding: "utf8",
		flag: "wx",
	});
	await rename(temporary, path);
	return path;
}

export class ApiError extends Error {
	constructor(status, code, message) {
		super(message);
		this.name = "ApiError";
		this.status = status;
		this.code = code;
	}
}

export class ExperimentStore {
	constructor({
		dataRoot,
		protocolPath,
		allowConditionOverride = false,
		allowPilotRuns = allowConditionOverride,
	}) {
		this.dataRoot = resolve(dataRoot);
		this.protocolPath = resolve(protocolPath);
		this.allowConditionOverride = Boolean(allowConditionOverride);
		this.allowPilotRuns = Boolean(allowPilotRuns);
		this.runsRoot = join(this.dataRoot, "runs");
		this.allocationPath = join(this.dataRoot, "stage1_allocation.json");
		this.stageTwoAllocationPath = join(this.dataRoot, "stage2_allocation.json");
		this.protocol = null;
		this.mutationQueue = Promise.resolve();
	}

	async init() {
		await mkdir(this.runsRoot, { recursive: true });
		this.protocol = await readJson(this.protocolPath);
		const conditions = this.protocol?.stage1?.conditions;
		if (
			!Array.isArray(conditions)
			|| conditions.length !== STAGE_ONE_CONDITIONS.length
			|| !STAGE_ONE_CONDITIONS.every((condition) => conditions.includes(condition))
		) {
			throw new Error(
				"experiment_protocol.json must define the five Stage 1 conditions.",
			);
		}
		return this;
	}

	queueMutation(operation) {
		const result = this.mutationQueue.then(operation, operation);
		this.mutationQueue = result.catch(() => {});
		return result;
	}

	runDirectory(runId) {
		if (!RUN_ID_PATTERN.test(runId)) {
			throw new ApiError(400, "invalid_run_id", "The run identifier is invalid.");
		}
		return join(this.runsRoot, runId);
	}

	recordPath(runId) {
		return join(this.runDirectory(runId), "record.json");
	}

	async readRecord(runId) {
		try {
			return await readJson(this.recordPath(runId));
		} catch (error) {
			if (error?.code === "ENOENT") {
				throw new ApiError(404, "run_not_found", "The experiment run was not found.");
			}
			throw error;
		}
	}

	authenticate(record, token) {
		const supplied = String(token ?? "");
		if (!supplied || tokenHash(supplied) !== record.resumeTokenHash) {
			throw new ApiError(401, "invalid_run_token", "The run token is missing or invalid.");
		}
	}

	async allocateStageOneCondition() {
		const initialCounts = Object.fromEntries(
			STAGE_ONE_CONDITIONS.map((condition) => [condition, 0]),
		);
		const allocation = await readJson(this.allocationPath, {
			schemaVersion: 1,
			remainingBlock: [],
			assignedCounts: initialCounts,
			updatedAt: null,
		});
		if (!Array.isArray(allocation.remainingBlock)) {
			allocation.remainingBlock = [];
		}
		if (!allocation.remainingBlock.length) {
			allocation.remainingBlock = shuffle(STAGE_ONE_CONDITIONS);
		}
		const condition = allocation.remainingBlock.pop();
		allocation.assignedCounts = {
			...initialCounts,
			...(allocation.assignedCounts || {}),
		};
		allocation.assignedCounts[condition] += 1;
		allocation.updatedAt = isoNow();
		await writeJsonAtomic(this.allocationPath, allocation);
		return condition;
	}

	async allocateStageTwoOrder() {
		const orders = this.protocol?.stage2?.counterbalanceOrders || [];
		if (!Array.isArray(orders) || !orders.length) {
			return null;
		}
		const byId = new Map(orders.map((order) => [String(order?.id || ""), order]));
		if (byId.has("")) {
			throw new Error("Every Stage 2 counterbalance order needs a non-empty id.");
		}
		const ids = [...byId.keys()];
		const allocation = await readJson(this.stageTwoAllocationPath, {
			schemaVersion: 1,
			remainingBlock: [],
			assignedCounts: Object.fromEntries(ids.map((id) => [id, 0])),
			updatedAt: null,
		});
		if (!Array.isArray(allocation.remainingBlock) || !allocation.remainingBlock.length) {
			allocation.remainingBlock = shuffle(ids);
		}
		const id = allocation.remainingBlock.pop();
		allocation.assignedCounts = {
			...Object.fromEntries(ids.map((orderId) => [orderId, 0])),
			...(allocation.assignedCounts || {}),
		};
		allocation.assignedCounts[id] += 1;
		allocation.updatedAt = isoNow();
		await writeJsonAtomic(this.stageTwoAllocationPath, allocation);
		return byId.get(id);
	}

	async createRun(input = {}) {
		return this.queueMutation(async () => {
			const stage = sanitizeString(input.stage, 16);
			if (!VALID_STAGES.has(stage)) {
				throw new ApiError(400, "invalid_stage", "Stage must be stage1 or stage2.");
			}
			const participantCode = sanitizeString(input.participantCode, 128);
			if (!participantCode) {
				throw new ApiError(400, "participant_required", "An anonymous participant code is required.");
			}
			const protocolId = sanitizeString(
				input.protocolId || this.protocol?.id,
				128,
			);
			if (!protocolId || protocolId !== this.protocol?.id) {
				throw new ApiError(400, "protocol_mismatch", "The protocol identifier does not match the server.");
			}
			const readyForDataCollection = input.readyForDataCollection === true;
			const pilotRun = input.pilotRun === true;
			if (!readyForDataCollection && !(pilotRun && this.allowPilotRuns)) {
				throw new ApiError(
					409,
					"session_not_ready",
					"The session failed readiness checks. Only an explicitly enabled pilot server may accept this run.",
				);
			}

			let condition = "stage2";
			let assignmentMethod = "server_stage2";
			let stage2Order = null;
			if (stage === "stage1") {
				const override = sanitizeString(input.conditionOverride, 32);
				if (override) {
					if (!this.allowConditionOverride) {
						throw new ApiError(403, "override_disabled", "Condition overrides are disabled on this server.");
					}
					if (!STAGE_ONE_CONDITIONS.includes(override)) {
						throw new ApiError(400, "invalid_condition", "The requested condition is invalid.");
					}
					condition = override;
					assignmentMethod = "server_fixed_qa";
				} else {
					condition = await this.allocateStageOneCondition();
					assignmentMethod = "server_balanced_block";
				}
			} else {
				stage2Order = await this.allocateStageTwoOrder();
				assignmentMethod = stage2Order
					? "server_stage2_balanced_order"
					: "server_stage2";
			}

			const resumeToken = randomBytes(32).toString("base64url");
			const runId = `ss-${Date.now().toString(36)}-${randomUUID()}`;
			const now = isoNow();
			const record = {
				schemaVersion: 1,
				runId,
				resumeTokenHash: tokenHash(resumeToken),
				protocolId,
				stage,
				condition,
				assignmentMethod,
				stage2Order,
				participantCode,
				status: "active",
				revision: 0,
				eventCount: 0,
				acceptedEventBatchIds: [],
				sessionId: sanitizeString(input.sessionId, 256),
				sessionUrl: sanitizeString(input.sessionUrl, 4096),
				trainingSessionUrl: sanitizeString(input.trainingSessionUrl, 4096),
				readyForDataCollection,
				pilotRun,
				draft: {},
				createdAt: now,
				updatedAt: now,
				completedAt: null,
			};
			await writeJsonAtomic(this.recordPath(runId), record);
			return { ...publicRun(record, true), resumeToken };
		});
	}

	async resumeRun(runId, token) {
		const record = await this.readRecord(runId);
		this.authenticate(record, token);
		return publicRun(record, true);
	}

	async saveDraft(runId, token, draft) {
		return this.queueMutation(async () => {
			const record = await this.readRecord(runId);
			this.authenticate(record, token);
			if (record.status !== "active") {
				throw new ApiError(409, "run_not_active", "A completed run cannot be changed.");
			}
			if (!draft || typeof draft !== "object" || Array.isArray(draft)) {
				throw new ApiError(400, "invalid_draft", "Draft must be a JSON object.");
			}
			record.draft = draft;
			record.revision += 1;
			record.updatedAt = isoNow();
			await writeJsonAtomic(this.recordPath(runId), record);
			return publicRun(record);
		});
	}

	async appendEvents(runId, token, batchId, events) {
		return this.queueMutation(async () => {
			const record = await this.readRecord(runId);
			this.authenticate(record, token);
			if (record.status !== "active") {
				throw new ApiError(409, "run_not_active", "A completed run cannot accept events.");
			}
			if (!BATCH_ID_PATTERN.test(String(batchId ?? ""))) {
				throw new ApiError(400, "invalid_batch_id", "The event batch identifier is invalid.");
			}
			if (!Array.isArray(events) || events.length > 500) {
				throw new ApiError(400, "invalid_events", "Events must be an array of at most 500 items.");
			}
			if (events.some((event) => !event || typeof event !== "object" || Array.isArray(event))) {
				throw new ApiError(400, "invalid_event", "Every event must be a JSON object.");
			}
			if (record.acceptedEventBatchIds.includes(batchId)) {
				return { duplicate: true, eventCount: record.eventCount };
			}
			const envelope = {
				batchId,
				receivedAt: isoNow(),
				events,
			};
			await appendFile(
				join(this.runDirectory(runId), "events.ndjson"),
				`${JSON.stringify(envelope)}\n`,
				"utf8",
			);
			record.acceptedEventBatchIds.push(batchId);
			record.eventCount += events.length;
			record.updatedAt = envelope.receivedAt;
			await writeJsonAtomic(this.recordPath(runId), record);
			return { duplicate: false, eventCount: record.eventCount };
		});
	}

	async completeRun(runId, token, submission) {
		return this.queueMutation(async () => {
			const record = await this.readRecord(runId);
			this.authenticate(record, token);
			if (record.status === "completed") {
				return publicRun(record);
			}
			if (!submission || typeof submission !== "object" || Array.isArray(submission)) {
				throw new ApiError(400, "invalid_submission", "Submission must be a JSON object.");
			}
			if (
				String(submission.runId ?? "") !== runId
				|| String(submission.stage ?? "") !== record.stage
				|| String(submission.condition ?? "") !== record.condition
			) {
				throw new ApiError(409, "submission_mismatch", "Submission identifiers do not match the run.");
			}
			if (
				submission.readyForDataCollection !== true
				&& !record.pilotRun
			) {
				throw new ApiError(
					409,
					"submission_not_ready",
					"A research submission cannot complete after failing readiness checks.",
				);
			}
			const completedAt = isoNow();
			await writeJsonAtomic(
				join(this.runDirectory(runId), "submission.json"),
				{
					receivedAt: completedAt,
					submission,
				},
			);
			record.status = "completed";
			record.completedAt = completedAt;
			record.updatedAt = completedAt;
			record.hasSubmission = true;
			await writeJsonAtomic(this.recordPath(runId), record);
			return publicRun(record);
		});
	}
}

function sendJson(response, status, value, extraHeaders = {}) {
	const body = `${JSON.stringify(value)}\n`;
	response.writeHead(status, {
		"Content-Type": "application/json; charset=utf-8",
		"Content-Length": Buffer.byteLength(body),
		"Cache-Control": "no-store",
		"X-Content-Type-Options": "nosniff",
		...extraHeaders,
	});
	response.end(body);
}

async function readRequestJson(request) {
	let size = 0;
	const chunks = [];
	for await (const chunk of request) {
		size += chunk.length;
		if (size > MAX_BODY_BYTES) {
			throw new ApiError(413, "body_too_large", "The request body is too large.");
		}
		chunks.push(chunk);
	}
	if (!chunks.length) {
		return {};
	}
	try {
		return JSON.parse(Buffer.concat(chunks).toString("utf8"));
	} catch {
		throw new ApiError(400, "invalid_json", "The request body is not valid JSON.");
	}
}

function runToken(request) {
	return request.headers["x-sandstories-run-token"] || "";
}

export function createExperimentApi(store) {
	return async function handleExperimentApi(request, response, url) {
		const pathname = url.pathname;
		if (!pathname.startsWith("/api/experiment/")) {
			return false;
		}
		try {
			if (request.method === "GET" && pathname === "/api/experiment/health") {
				sendJson(response, 200, {
					ok: true,
					service: "sandstories-experiment",
					protocolId: store.protocol?.id || "",
					persistence: "filesystem",
				});
				return true;
			}
			if (request.method === "POST" && pathname === "/api/experiment/runs") {
				const result = await store.createRun(await readRequestJson(request));
				sendJson(response, 201, result);
				return true;
			}

			const match = pathname.match(
				/^\/api\/experiment\/runs\/([^/]+)(?:\/(draft|events|complete))?$/,
			);
			if (!match) {
				throw new ApiError(404, "api_not_found", "The experiment API route was not found.");
			}
			const runId = decodeURIComponent(match[1]);
			const action = match[2] || "resume";
			if (request.method === "GET" && action === "resume") {
				sendJson(response, 200, await store.resumeRun(runId, runToken(request)));
				return true;
			}
			if (request.method === "PUT" && action === "draft") {
				const body = await readRequestJson(request);
				sendJson(response, 200, await store.saveDraft(
					runId,
					runToken(request),
					body.draft,
				));
				return true;
			}
			if (request.method === "POST" && action === "events") {
				const body = await readRequestJson(request);
				sendJson(response, 200, await store.appendEvents(
					runId,
					runToken(request),
					body.batchId,
					body.events,
				));
				return true;
			}
			if (request.method === "POST" && action === "complete") {
				const body = await readRequestJson(request);
				sendJson(response, 200, await store.completeRun(
					runId,
					runToken(request),
					body.submission,
				));
				return true;
			}
			throw new ApiError(405, "method_not_allowed", "The method is not allowed for this route.");
		} catch (error) {
			const status = Number(error?.status || 500);
			if (status >= 500) {
				console.error(`Experiment API error: ${error?.stack || error}`);
			}
			sendJson(response, status, {
				error: error?.code || "internal_error",
				message: status >= 500 ? "The experiment service failed." : error.message,
			});
			return true;
		}
	};
}
