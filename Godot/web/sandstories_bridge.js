(function bootstrapSandStoriesBridge(global) {
	"use strict";

	if (global.SandStories) {
		return;
	}

	const EVENT_PREFIX = "sandstories:";
	const query = new URLSearchParams(global.location.search);
	const allowedParentOrigin = query.get("parent_origin") || global.location.origin;
	const pending = new Map();
	const queued = [];
	let sequence = 0;
	let currentState = null;
	let readyResolve;
	const ready = new Promise((resolve) => {
		readyResolve = resolve;
	});

	function nextRequestId() {
		sequence += 1;
		return `web-${Date.now()}-${sequence}`;
	}

	function godotCallback() {
		return global.__sandstoriesGodotCommand;
	}

	function sendRaw(message) {
		const callback = godotCallback();
		if (typeof callback !== "function") {
			queued.push(message);
			return;
		}
		callback(JSON.stringify(message));
	}

	function flushQueued() {
		const callback = godotCallback();
		if (typeof callback !== "function") {
			return false;
		}
		while (queued.length) {
			callback(JSON.stringify(queued.shift()));
		}
		return true;
	}

	function command(commandName, payload = {}, options = {}) {
		const requestId = options.requestId || nextRequestId();
		const timeoutMs = options.timeoutMs || 60000;
		const result = new Promise((resolve, reject) => {
			const timeout = global.setTimeout(() => {
				pending.delete(requestId);
				reject(new Error(`Godot command timed out: ${commandName}`));
			}, timeoutMs);
			pending.set(requestId, { resolve, reject, timeout });
		});
		sendRaw({
			requestId,
			command: commandName,
			payload,
		});
		return result;
	}

	function emit(kind, detail) {
		global.dispatchEvent(new CustomEvent(`${EVENT_PREFIX}${kind}`, {
			detail,
		}));
		if (global.parent !== global) {
			global.parent.postMessage({
				type: `${EVENT_PREFIX}${kind}`,
				detail,
			}, allowedParentOrigin);
		}
	}

	function decodeEnvelope(encoded) {
		const binary = global.atob(encoded);
		const bytes = Uint8Array.from(binary, (character) => (
			character.charCodeAt(0)
		));
		return JSON.parse(new TextDecoder().decode(bytes));
	}

	const api = {
		ready,
		command,
		get state() {
			return currentState;
		},
		getState() {
			return command("get_state");
		},
		play() {
			return command("set_playing", { playing: true });
		},
		pause() {
			return command("set_playing", { playing: false });
		},
		togglePlayback() {
			return command("toggle_playback");
		},
		seek(seconds) {
			return command("seek", { seconds });
		},
		seekNormalized(progress) {
			return command("seek_normalized", { progress });
		},
		loadSession(url) {
			return command("load_session", { url }, { timeoutMs: 120000 });
		},
		setCondition(condition) {
			return command("set_condition", { condition });
		},
		setLayer(layer, visible) {
			return command("set_layer", { layer, visible });
		},
		setSurfaceControl(key, value) {
			return command("set_surface_control", { key, value });
		},
		setView(preset) {
			return command("set_view", { preset });
		},
		setFocusMode(enabled) {
			return command("set_focus_mode", { enabled });
		},
		markEvidence() {
			return command("mark_evidence");
		},
		recordEvent(payload) {
			return command("record_host_event", payload);
		},
		__receiveBase64(encoded) {
			let envelope;
			try {
				envelope = decodeEnvelope(encoded);
			} catch (error) {
				console.error("Cannot decode SandStories bridge message", error);
				return;
			}
			flushQueued();
			const kind = envelope.kind;
			const detail = envelope.detail || {};
			if (kind === "ready" || kind === "state") {
				currentState = detail;
			}
			if (kind === "ready") {
				readyResolve(detail);
			}
			if (kind === "command_result") {
				const request = pending.get(detail.requestId);
				if (request) {
					global.clearTimeout(request.timeout);
					pending.delete(detail.requestId);
					if (detail.ok) {
						request.resolve(detail.data);
					} else {
						request.reject(new Error(
							detail.error || "Godot command failed",
						));
					}
				}
			}
			emit(kind, detail);
		},
	};

	global.SandStories = api;

	global.addEventListener("message", (event) => {
		if (
			event.source !== global.parent
			|| event.origin !== allowedParentOrigin
		) {
			return;
		}
		const message = event.data;
		if (!message || message.type !== `${EVENT_PREFIX}command`) {
			return;
		}
		sendRaw({
			requestId: String(message.requestId || nextRequestId()),
			command: String(message.command || ""),
			payload: (
				message.payload
				&& typeof message.payload === "object"
			) ? message.payload : {},
		});
	});

	const registrationTimer = global.setInterval(() => {
		if (flushQueued()) {
			global.clearInterval(registrationTimer);
		}
	}, 50);
}(window));
