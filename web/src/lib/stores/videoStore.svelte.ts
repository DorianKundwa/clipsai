import type { Aspect, Look, TrimOptions } from '../video';

export interface VideoSource {
	file: File;
	name: string;
	size: number;
	type: string;
	/** Object URL for the <video> element. Owned by this store. */
	url: string;
	duration: number;
	width: number;
	height: number;
}

export type JobStatus = 'queued' | 'rendering' | 'done' | 'error';

/** What IndiePost reported for a finished post. */
export interface PublishReceipt {
	platforms: string[];
	links: string[];
	at: number;
}

export interface RenderJob {
	id: string;
	label: string;
	fileName: string;
	status: JobStatus;
	/** 0..1 */
	progress: number;
	options: TrimOptions;
	sourceName: string;
	createdAt: number;
	startedAt: number | null;
	finishedAt: number | null;
	size: number | null;
	url: string | null;
	error: string | null;
	published: PublishReceipt | null;
}

/** Shortest clip we will render; below this ffmpeg produces empty output. */
export const MIN_CLIP = 0.25;

let counter = 0;

function uid(): string {
	counter += 1;
	return `job-${Date.now().toString(36)}-${counter.toString(36)}`;
}

function safeName(name: string): string {
	return name.replace(/\.[^.]+$/, '').replace(/[^\w -]+/g, '').trim() || 'clip';
}

export function describeError(error: unknown): string {
	if (error instanceof Error) return error.message;
	if (typeof error === 'string') return error;
	return 'Something went wrong while rendering';
}

/**
 * Module-scoped singleton: SvelteKit keeps client modules alive across route
 * changes, so the loaded video, trim points and render queue survive
 * navigating between /, /studio and /exports.
 */
class VideoStore {
	source = $state<VideoSource | null>(null);

	/** Playhead position, seconds. Written by the studio's rAF loop. */
	currentTime = $state(0);
	playing = $state(false);

	/** Trim range, seconds. */
	inPoint = $state(0);
	outPoint = $state(0);

	look = $state<Look>('none');
	aspect = $state<Aspect>('source');

	jobs = $state<RenderJob[]>([]);

	duration = $derived(this.source?.duration ?? 0);
	trimLength = $derived(Math.max(0, this.outPoint - this.inPoint));
	canExport = $derived(
		this.source !== null && this.trimLength >= MIN_CLIP && this.trimLength <= this.duration + 0.01
	);
	activeJobs = $derived(
		this.jobs.filter((job) => job.status === 'queued' || job.status === 'rendering').length
	);
	finishedJobs = $derived(this.jobs.filter((job) => job.status === 'done'));
	exportedBytes = $derived(
		this.finishedJobs.reduce((total, job) => total + (job.size ?? 0), 0)
	);
	options = $derived<TrimOptions>({
		start: this.inPoint,
		end: this.outPoint,
		look: this.look,
		aspect: this.aspect
	});

	readonly seekListeners = new Set<(time: number) => void>();
	#pendingRange: { start: number; end: number } | null = null;

	/**
	 * The <video> element lives in the studio, not here, so the store asks
	 * whoever is mounted to move the playhead.
	 */
	onSeek(listener: (time: number) => void): () => void {
		this.seekListeners.add(listener);
		return () => this.seekListeners.delete(listener);
	}

	attach(file: File): void {
		if (this.source) URL.revokeObjectURL(this.source.url);
		this.#pendingRange = null;

		this.source = {
			file,
			name: file.name,
			size: file.size,
			type: file.type,
			url: URL.createObjectURL(file),
			duration: 0,
			width: 0,
			height: 0
		};

		this.currentTime = 0;
		this.inPoint = 0;
		this.outPoint = 0;
		this.playing = false;
	}

	/** Load a clip or source file rendered by the Python pipeline into Studio. */
	async attachFromUrl(
		url: string,
		fileName: string,
		trimRange?: { start?: number; end?: number }
	): Promise<void> {
		const response = await fetch(url);
		if (!response.ok) throw new Error(`Could not load clip (HTTP ${response.status}).`);
		const blob = await response.blob();
		const file = new File([blob], fileName, { type: blob.type || 'video/mp4' });
		this.attach(file);
		if (trimRange && (trimRange.start !== undefined || trimRange.end !== undefined)) {
			this.#pendingRange = {
				start: Math.max(0, Number(trimRange.start ?? 0)),
				end: Math.max(0, Number(trimRange.end ?? 0))
			};
		}
	}

	/** Import a Python-rendered clip straight into Exports for download or IndiePost publish. */
	async importExportFromUrl(
		url: string,
		label: string,
		fileName: string,
		options: Partial<TrimOptions> = {}
	): Promise<RenderJob> {
		const response = await fetch(url);
		if (!response.ok) throw new Error(`Could not load export (HTTP ${response.status}).`);
		const blob = await response.blob();
		const now = Date.now();
		const job: RenderJob = {
			id: uid(),
			label: label || safeName(fileName),
			fileName,
			status: 'done',
			progress: 1,
			options: {
				start: options.start ?? 0,
				end: options.end ?? 0,
				aspect: options.aspect ?? '9:16',
				look: options.look ?? 'none'
			},
			sourceName: label || fileName,
			createdAt: now,
			startedAt: now,
			finishedAt: now,
			size: blob.size,
			url: URL.createObjectURL(blob),
			error: null,
			published: null
		};
		this.jobs = [job, ...this.jobs];
		return job;
	}

	/** Called once the browser has read the media metadata. */
	setDuration(seconds: number): void {
		if (!this.source || !Number.isFinite(seconds)) return;

		this.source.duration = seconds;
		if (this.#pendingRange) {
			const { start, end } = this.#pendingRange;
			this.#pendingRange = null;
			const clampedStart = Math.min(Math.max(0, start), Math.max(0, seconds - MIN_CLIP));
			const clampedEnd = Math.min(Math.max(clampedStart + MIN_CLIP, end || seconds), seconds);
			this.inPoint = clampedStart;
			this.outPoint = clampedEnd;
			this.currentTime = clampedStart;
			for (const listener of this.seekListeners) listener(clampedStart);
			return;
		}
		this.inPoint = 0;
		this.outPoint = seconds;
		this.currentTime = Math.min(this.currentTime, seconds);
	}

	setDimensions(width: number, height: number): void {
		if (!this.source) return;
		this.source.width = width;
		this.source.height = height;
	}

	detach(): void {
		if (this.source) URL.revokeObjectURL(this.source.url);
		this.source = null;
		this.currentTime = 0;
		this.inPoint = 0;
		this.outPoint = 0;
		this.playing = false;
	}

	seek(time: number): void {
		const clamped = Math.min(Math.max(time, 0), this.duration || 0);
		this.currentTime = clamped;
		for (const listener of this.seekListeners) listener(clamped);
	}

	setIn(time: number): void {
		const ceiling = Math.max(0, this.outPoint - MIN_CLIP);
		this.inPoint = Math.min(Math.max(time, 0), ceiling);
		if (this.currentTime < this.inPoint) this.seek(this.inPoint);
	}

	setOut(time: number): void {
		const floor = Math.min(this.duration, this.inPoint + MIN_CLIP);
		this.outPoint = Math.min(Math.max(time, floor), this.duration);
		if (this.currentTime > this.outPoint) this.seek(this.outPoint);
	}

	createJob(options: TrimOptions): RenderJob {
		const source = this.source;
		const job: RenderJob = {
			id: uid(),
			label: `${safeName(source?.name ?? 'clip')} ${this.inPoint.toFixed(2)}s–${this.outPoint.toFixed(2)}s`,
			fileName: `${safeName(source?.name ?? 'clip')}-${Math.round(this.inPoint * 1000)}.mp4`,
			status: 'queued',
			progress: 0,
			options: { ...options },
			sourceName: source?.name ?? 'clip',
			createdAt: Date.now(),
			startedAt: null,
			finishedAt: null,
			size: null,
			url: null,
			error: null,
			published: null
		};

		this.jobs = [job, ...this.jobs];
		return job;
	}

	private patch(id: string, changes: Partial<RenderJob>): void {
		const index = this.jobs.findIndex((job) => job.id === id);
		if (index === -1) return;
		this.jobs[index] = { ...this.jobs[index], ...changes };
	}

	startJob(id: string): void {
		this.patch(id, { status: 'rendering', startedAt: Date.now() });
	}

	setProgress(id: string, ratio: number): void {
		const clamped = Math.min(Math.max(ratio, 0), 0.999);
		this.patch(id, { progress: clamped });
	}

	completeJob(id: string, blob: Blob): void {
		const existing = this.jobs.find((job) => job.id === id);
		if (existing?.url) URL.revokeObjectURL(existing.url);

		this.patch(id, {
			status: 'done',
			progress: 1,
			size: blob.size,
			url: URL.createObjectURL(blob),
			finishedAt: Date.now(),
			error: null
		});
	}

	/** Record a successful post so the exports list can show where it went. */
	markPublished(id: string, receipt: PublishReceipt): void {
		this.patch(id, { published: receipt });
	}

	failJob(id: string, error: unknown): void {
		this.patch(id, {
			status: 'error',
			progress: 0,
			error: describeError(error),
			finishedAt: Date.now()
		});
	}

	removeJob(id: string): void {
		const job = this.jobs.find((entry) => entry.id === id);
		if (job?.url) URL.revokeObjectURL(job.url);
		this.jobs = this.jobs.filter((entry) => entry.id !== id);
	}

	clearFinished(): void {
		for (const job of this.jobs) {
			if (job.status === 'done' && job.url) URL.revokeObjectURL(job.url);
		}
		this.jobs = this.jobs.filter((job) => job.status !== 'done');
	}
}

export const videoStore = new VideoStore();
