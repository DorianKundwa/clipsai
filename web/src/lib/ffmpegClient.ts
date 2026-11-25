import type { TrimOptions } from './video';
import type { WorkerPayload, WorkerRequest, WorkerResponse } from './workers/ffmpeg.worker';

export interface RenderHandlers {
	/** Fired once the worker actually starts encoding, after any queue wait. */
	onStart?: () => void;
	/** 0..1, driven by ffmpeg's own progress report. */
	onProgress?: (ratio: number) => void;
	onLog?: (message: string) => void;
}

interface Pending {
	resolve: (value: never) => void;
	reject: (reason: Error) => void;
	handlers: RenderHandlers;
}

let worker: Worker | null = null;
let sequence = 0;
let queueTail: Promise<unknown> = Promise.resolve();
let loadPromise: Promise<void> | null = null;
const pending = new Map<number, Pending>();

/** True when COOP/COEP are in effect, i.e. when the multithreaded core can run. */
export function isCrossOriginIsolated(): boolean {
	return typeof window !== 'undefined' && window.crossOriginIsolated === true;
}

function getWorker(): Worker {
	if (worker) return worker;

	worker = new Worker(new URL('./workers/ffmpeg.worker.ts', import.meta.url), {
		type: 'module',
		name: 'ffmpeg-render'
	});

	worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
		const message = event.data;
		const entry = pending.get(message.id);
		if (!entry) return;

		switch (message.type) {
			case 'loaded':
				pending.delete(message.id);
				entry.resolve(undefined as never);
				break;
			case 'start':
				entry.handlers.onStart?.();
				break;
			case 'progress':
				entry.handlers.onProgress?.(message.ratio);
				break;
			case 'log':
				// ffmpeg is verbose; keep it at debug level unless the caller wants it.
				if (entry.handlers.onLog) entry.handlers.onLog(message.message);
				else console.debug('[ffmpeg]', message.message);
				break;
			case 'done':
				pending.delete(message.id);
				entry.resolve(message as never);
				break;
			case 'error':
				pending.delete(message.id);
				entry.reject(new Error(message.message));
				break;
		}
	};

	worker.onerror = (event) => {
		const detail = event.message || 'The FFmpeg worker failed to start';
		for (const [id, entry] of pending) {
			pending.delete(id);
			entry.reject(new Error(detail));
		}
		// Drop the broken worker so the next attempt re-creates it.
		worker?.terminate();
		worker = null;
		loadPromise = null;
	};

	return worker;
}

function request<T>(payload: WorkerPayload, handlers: RenderHandlers = {}): Promise<T> {
	const id = ++sequence;
	const target = getWorker();

	return new Promise<T>((resolve, reject) => {
		pending.set(id, {
			resolve: resolve as (value: never) => void,
			reject,
			handlers
		});
		target.postMessage({ ...payload, id } satisfies WorkerRequest);
	});
}

/**
 * Loads the wasm core ahead of the first export so the click-to-encode latency
 * is mostly gone. Safe to call repeatedly.
 */
export function preload(): Promise<void> {
	if (!loadPromise) {
		loadPromise = request<void>({ type: 'load' }).catch((error: unknown) => {
			loadPromise = null;
			throw error;
		});
	}
	return loadPromise;
}

/**
 * Encodes one clip. Jobs are serialised through a single FFmpeg instance —
 * one MEMFS, one thread pool — so a queue of exports runs back to back instead
 * of competing for memory.
 */
export function renderClip(
	file: File,
	options: TrimOptions,
	handlers: RenderHandlers = {}
): Promise<Blob> {
	const task = async (): Promise<Blob> => {
		await preload();
		const result = await request<{ buffer: ArrayBuffer; mimeType: string }>(
			{ type: 'render', file, options },
			handlers
		);
		return new Blob([result.buffer], { type: result.mimeType });
	};

	const run = queueTail.then(task, task);
	queueTail = run.then(
		() => undefined,
		() => undefined
	);
	return run;
}
