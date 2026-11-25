import { FFmpeg, FFFSType } from '@ffmpeg/ffmpeg';
import { fetchFile } from '@ffmpeg/util';
import type { TrimOptions } from '../video';

/**
 * Messages in: one job at a time, tagged with an id so late progress events
 * from an abandoned job can be ignored by the client.
 */
export type WorkerPayload =
	| { type: 'load' }
	| { type: 'render'; file: File; options: TrimOptions };

export type WorkerRequest = WorkerPayload & { id: number };

export type WorkerResponse =
	| { id: number; type: 'loaded' }
	| { id: number; type: 'start' }
	| { id: number; type: 'progress'; ratio: number; time: number }
	| { id: number; type: 'log'; message: string }
	| { id: number; type: 'done'; buffer: ArrayBuffer; mimeType: string }
	| { id: number; type: 'error'; message: string };

/**
 * The core is served from static/ffmpeg (see scripts/sync-ffmpeg-core.mjs) so
 * these paths are stable across dev and production builds.
 */
const coreURL = new URL('/ffmpeg/ffmpeg-core.js', self.location.origin).href;
const wasmURL = new URL('/ffmpeg/ffmpeg-core.wasm', self.location.origin).href;
const workerURL = new URL('/ffmpeg/ffmpeg-core.worker.js', self.location.origin).href;

let engine: FFmpeg | null = null;
let loading: Promise<FFmpeg> | null = null;
let activeId: number | null = null;
let activeDuration = 0;

const post = (message: WorkerResponse, transfer?: Transferable[]) => {
	if (transfer) self.postMessage(message, { transfer });
	else self.postMessage(message);
};

function filtersFor({ look, aspect }: TrimOptions): string[] {
	const filters: string[] = [];

	if (aspect !== 'source') {
		const [width, height] =
			aspect === '9:16' ? [1080, 1920] : aspect === '1:1' ? [1080, 1080] : [1920, 1080];
		// Fill the target frame, then crop the overflow: no letterboxing, and it
		// works for both landscape and portrait sources.
		filters.push(`scale=${width}:${height}:force_original_aspect_ratio=increase:flags=lanczos`);
		filters.push(`crop=${width}:${height}`);
	}

	switch (look) {
		case 'warm':
			filters.push('colorbalance=rs=0.12:gs=0.02:bs=-0.12');
			break;
		case 'cool':
			filters.push('colorbalance=rs=-0.12:bs=0.12');
			break;
		case 'punch':
			filters.push('eq=contrast=1.12:saturation=1.25');
			break;
		case 'mono':
			filters.push('hue=s=0');
			break;
	}

	return filters;
}

async function ensureEngine(): Promise<FFmpeg> {
	if (engine?.loaded) return engine;

	if (!loading) {
		const instance = engine ?? new FFmpeg();
		engine = instance;

		instance.on('progress', ({ progress, time }) => {
			if (activeId === null) return;

			// ffmpeg's own ratio is computed against the whole input, which is
			// useless when we trim. The reported output timestamp is accurate,
			// so prefer that and keep ffmpeg's value only if it is further along.
			const elapsed = Math.abs(time) / 1_000_000;
			const fromTime = activeDuration > 0 ? elapsed / activeDuration : 0;
			const ratio = Math.min(Math.max(Number.isFinite(progress) ? progress : 0, fromTime), 1);

			post({ id: activeId, type: 'progress', ratio, time });
		});

		instance.on('log', ({ message }) => {
			if (activeId === null || !message) return;
			post({ id: activeId, type: 'log', message });
		});

		loading = instance
			.load({ coreURL, wasmURL, workerURL })
			.then(() => instance)
			.catch((error: unknown) => {
				loading = null;
				engine = null;
				throw error;
			});
	}

	return await loading;
}

async function render(id: number, file: File, options: TrimOptions): Promise<void> {
	const ffmpeg = await ensureEngine();
	activeId = id;
	post({ id, type: 'start' });

	const mountDir = `/work-${id}`;
	const fallbackInput = `input-${id}`;
	const output = `output-${id}.mp4`;
	const duration = Math.max(0.05, options.end - options.start);
	const filters = filtersFor(options);
	activeDuration = duration;

	let input = fallbackInput;
	let mounted = false;
	let wroteInput = false;

	try {
		try {
			await ffmpeg.createDir(mountDir);
			const useDirectFile = Boolean(file.name) && !file.name.includes('/');
			const entryName = useDirectFile ? file.name : 'source';
			const mountData = useDirectFile
				? { files: [file] }
				: { blobs: [{ name: entryName, data: file }] };
			await ffmpeg.mount(FFFSType.WORKERFS, mountData, mountDir);
			input = `${mountDir}/${entryName}`;
			mounted = true;
		} catch {
			await ffmpeg.deleteDir(mountDir).catch(() => undefined);
			await ffmpeg.writeFile(fallbackInput, await fetchFile(file));
			input = fallbackInput;
			wroteInput = true;
		}

		const args = [
			'-hide_banner',
			'-nostdin',
			// Fast input seek, then an exact duration on the output: `-ss` before
			// `-i` avoids decoding the whole file up to the in-point.
			'-ss',
			options.start.toFixed(3),
			'-i',
			input,
			'-t',
			duration.toFixed(3)
		];

		if (filters.length) args.push('-vf', filters.join(','));

		args.push(
			'-c:v',
			'libx264',
			'-preset',
			'veryfast',
			// x264's auto/slice threading deadlocks inside the wasm pthread pool;
			// one encoder thread is slower but always finishes. Decode and the
			// filter graph still use the multithreaded core.
			'-threads',
			'1',
			'-crf',
			'23',
			'-pix_fmt',
			'yuv420p',
			'-c:a',
			'aac',
			'-b:a',
			'160k',
			'-movflags',
			'+faststart',
			'-y',
			output
		);

		const code = await ffmpeg.exec(args);
		if (code !== 0) throw new Error(`ffmpeg exited with code ${code}`);

		const data = await ffmpeg.readFile(output);
		if (typeof data === 'string') throw new Error('ffmpeg returned no video data');

		// Copy out of MEMFS into a standalone buffer the main thread can own.
		const buffer = data.buffer.slice(
			data.byteOffset,
			data.byteOffset + data.byteLength
		) as ArrayBuffer;

		post({ id, type: 'done', buffer, mimeType: 'video/mp4' }, [buffer]);
	} finally {
		activeId = null;
		if (mounted) {
			await ffmpeg.unmount(mountDir).catch(() => undefined);
			await ffmpeg.deleteDir(mountDir).catch(() => undefined);
		}
		if (wroteInput) {
			await ffmpeg.deleteFile(fallbackInput).catch(() => undefined);
		}
		await ffmpeg.deleteFile(output).catch(() => undefined);
	}
}

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
	const message = event.data;
	if (!message) return;

	try {
		switch (message.type) {
			case 'load':
				await ensureEngine();
				post({ id: message.id, type: 'loaded' });
				break;
			case 'render':
				await render(message.id, message.file, message.options);
				break;
		}
	} catch (error) {
		activeId = null;
		const text = error instanceof Error ? error.message : String(error);
		post({ id: message.id, type: 'error', message: text || 'Render failed' });
	}
};

