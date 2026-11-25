<script lang="ts">
	import { onMount } from 'svelte';
	import AccountTargets from '#lib/components/AccountTargets.svelte';
	import DropZone from '#lib/components/DropZone.svelte';
	import Timeline from '#lib/components/Timeline.svelte';
	import { isCrossOriginIsolated, preload, renderClip } from '#lib/ffmpegClient';
	import { describeError, videoStore } from '#lib/stores/videoStore.svelte';
	import { indiePost } from '#lib/stores/indiepost.svelte';
	import { targets } from '#lib/stores/targets.svelte';
	import { ASPECTS, LOOKS, formatBytes, formatDuration, formatTime } from '#lib/video';

	let videoEl = $state<HTMLVideoElement | null>(null);
	let stageEl = $state<HTMLDivElement | null>(null);
	let overlayEl = $state<HTMLCanvasElement | null>(null);

	let isolated = $state(true);
	let errorMessage = $state<string | null>(null);
	let justRendered = $state<string | null>(null);

	const source = $derived(videoStore.source);
	const aspect = $derived(ASPECTS.find((entry) => entry.id === videoStore.aspect) ?? ASPECTS[0]);
	const rendering = $derived(videoStore.jobs.find((job) => job.status === 'rendering') ?? null);
	const queued = $derived(videoStore.jobs.filter((job) => job.status === 'queued').length);

	/** Target rectangle for the crop guide, in canvas pixels. */
	function cropRect() {
		const video = videoEl;
		const stage = stageEl;
		if (!video || !stage) return null;

		const rect = stage.getBoundingClientRect();
		const ratio = aspect.ratio;
		if (!ratio || !video.videoWidth || !video.videoHeight) return null;

		// The <video> is object-fit: contain, so it may be letterboxed inside the
		// stage box. Map the crop into the pixels the frame actually occupies.
		const scale = Math.min(rect.width / video.videoWidth, rect.height / video.videoHeight);
		const frameWidth = video.videoWidth * scale;
		const frameHeight = video.videoHeight * scale;
		const frameX = (rect.width - frameWidth) / 2;
		const frameY = (rect.height - frameHeight) / 2;

		let width = frameWidth;
		let height = width / ratio;
		if (height > frameHeight) {
			height = frameHeight;
			width = height * ratio;
		}

		return {
			stage: rect,
			frame: { x: frameX, y: frameY, width: frameWidth, height: frameHeight },
			crop: {
				x: frameX + (frameWidth - width) / 2,
				y: frameY + (frameHeight - height) / 2,
				width,
				height
			}
		};
	}

	function drawOverlay(): void {
		const canvas = overlayEl;
		const geometry = cropRect();
		if (!canvas) return;

		const dpr = Math.min(window.devicePixelRatio || 1, 2);
		const width = canvas.clientWidth;
		const height = canvas.clientHeight;
		if (width === 0 || height === 0) return;

		if (canvas.width !== Math.round(width * dpr)) canvas.width = Math.round(width * dpr);
		if (canvas.height !== Math.round(height * dpr)) canvas.height = Math.round(height * dpr);

		const context = canvas.getContext('2d');
		if (!context) return;

		context.setTransform(dpr, 0, 0, dpr, 0, 0);
		context.clearRect(0, 0, width, height);
		if (!geometry) return;

		const { frame, crop } = geometry;

		// Dim everything the crop will throw away.
		context.fillStyle = 'rgba(4, 5, 7, 0.62)';
		context.fillRect(frame.x, frame.y, frame.width, crop.y - frame.y);
		context.fillRect(frame.x, crop.y + crop.height, frame.width, frame.y + frame.height - (crop.y + crop.height));
		context.fillRect(frame.x, crop.y, crop.x - frame.x, crop.height);
		context.fillRect(crop.x + crop.width, crop.y, frame.x + frame.width - (crop.x + crop.width), crop.height);

		context.strokeStyle = 'rgba(215, 255, 62, 0.85)';
		context.lineWidth = 1.5;
		context.strokeRect(crop.x, crop.y, crop.width, crop.height);

		// Rule-of-thirds guides inside the deliverable frame.
		context.strokeStyle = 'rgba(255, 255, 255, 0.16)';
		context.lineWidth = 1;
		for (let i = 1; i < 3; i += 1) {
			const x = crop.x + (crop.width / 3) * i;
			const y = crop.y + (crop.height / 3) * i;
			context.beginPath();
			context.moveTo(x, crop.y);
			context.lineTo(x, crop.y + crop.height);
			context.moveTo(crop.x, y);
			context.lineTo(crop.x + crop.width, y);
			context.stroke();
		}
	}

	onMount(() => {
		isolated = isCrossOriginIsolated();
		void indiePost.load();
		const stopSeek = videoStore.onSeek((time) => {
			const video = videoEl;
			if (video && Number.isFinite(time)) video.currentTime = time;
		});

		const observer = new ResizeObserver(() => drawOverlay());
		if (stageEl) observer.observe(stageEl);

		// Warm the wasm core so the first export starts immediately.
		if (isolated) void preload().catch(() => undefined);

		return () => {
			stopSeek();
			observer.disconnect();
		};
	});

	// Repaint the framing guide whenever the aspect, source or layout changes.
	$effect(() => {
		void videoStore.aspect;
		void videoStore.source;
		void stageEl;
		drawOverlay();
	});

	// Follow the destinations: TikTok/Reels want 9:16, YouTube long-form 16:9.
	$effect(() => {
		if (targets.autoFrame && targets.recommendedAspect) {
			videoStore.aspect = targets.recommendedAspect;
		}
	});

	// Drive the playhead from the media element, and loop the trim range.
	$effect(() => {
		if (!videoStore.playing) return;
		let frame = 0;

		const tick = () => {
			const video = videoEl;
			if (video) {
				videoStore.currentTime = video.currentTime;
				if (video.currentTime >= videoStore.outPoint) {
					video.currentTime = videoStore.inPoint;
					void video.play().catch(() => undefined);
				}
			}
			frame = requestAnimationFrame(tick);
		};

		frame = requestAnimationFrame(tick);
		return () => cancelAnimationFrame(frame);
	});

	function handleMetadata(event: Event): void {
		const video = event.currentTarget as HTMLVideoElement;
		videoStore.setDuration(video.duration);
		videoStore.setDimensions(video.videoWidth, video.videoHeight);
		videoStore.seek(0);
		drawOverlay();
	}

	function togglePlay(): void {
		const video = videoEl;
		if (!video) return;

		if (!video.paused) {
			video.pause();
			return;
		}

		if (video.currentTime < videoStore.inPoint || video.currentTime >= videoStore.outPoint) {
			video.currentTime = videoStore.inPoint;
		}

		void video.play().catch((error) => (errorMessage = describeError(error)));
	}

	function stepBy(seconds: number): void {
		videoStore.seek(videoStore.currentTime + seconds);
	}

	function setInFromPlayhead(): void {
		videoStore.setIn(videoStore.currentTime);
	}

	function setOutFromPlayhead(): void {
		videoStore.setOut(videoStore.currentTime);
	}

	async function exportClip(): Promise<void> {
		const current = videoStore.source;
		if (!current || !videoStore.canExport) return;

		errorMessage = null;
		justRendered = null;

		const options = { ...videoStore.options };
		const job = videoStore.createJob(options);

		try {
			const blob = await renderClip(current.file, options, {
				onStart: () => videoStore.startJob(job.id),
				onProgress: (ratio) => videoStore.setProgress(job.id, ratio),
				onLog: (text) => console.debug('[ffmpeg]', text)
			});
			videoStore.completeJob(job.id, blob);
			justRendered = job.id;
		} catch (error) {
			videoStore.failJob(job.id, error);
			errorMessage = describeError(error);
		}
	}
</script>

<svelte:head>
	<title>Studio — ClipsAI</title>
</svelte:head>

<div class="page">
	{#if !source}
		<section class="blank">
			<div>
				<span class="eyebrow">Studio</span>
				<h1>Load a clip to start editing</h1>
				<p class="muted">
					The editor decodes locally and keeps a single FFmpeg instance warm in a worker.
				</p>
			</div>
			<DropZone title="Drop footage here" subtitle="MP4, MOV, WebM or MKV · up to 2 GB" />
		</section>
	{:else}
		<div class="workspace">
			<section class="stage-col">
				<div class="stage-head">
					<div class="file">
						<strong>{source.name}</strong>
						<span class="mono muted">
							{formatBytes(source.size)}{#if source.duration} · {formatDuration(source.duration)}{/if}
							{#if source.width} · {source.width}×{source.height}{/if}
						</span>
					</div>
					<button class="btn btn-ghost btn-sm" onclick={() => videoStore.detach()}>Change clip</button>
				</div>

				<div class="stage" bind:this={stageEl}>
					<!-- svelte-ignore a11y_media_has_caption -->
					<video
						bind:this={videoEl}
						src={source.url}
						playsinline
						preload="metadata"
						onloadedmetadata={handleMetadata}
						onplay={() => (videoStore.playing = true)}
						onpause={() => (videoStore.playing = false)}
						onended={() => (videoStore.playing = false)}
					></video>

					{#if aspect.ratio}
						<canvas class="overlay" bind:this={overlayEl} aria-hidden="true"></canvas>
					{/if}

					<div class="badge mono">
						{formatTime(videoStore.currentTime)}
						<span class="dim">/ {formatTime(videoStore.duration)}</span>
					</div>
				</div>

				<div class="transport">
					<button class="btn btn-sm" onclick={togglePlay}>
						{videoStore.playing ? 'Pause' : 'Play'}
					</button>
					<button class="btn btn-ghost btn-sm" onclick={() => stepBy(-0.5)}>−0.5s</button>
					<button class="btn btn-ghost btn-sm" onclick={() => stepBy(0.5)}>+0.5s</button>
					<span class="spacer"></span>
					<button class="btn btn-ghost btn-sm" onclick={() => videoStore.seek(videoStore.inPoint)}>
						Jump to in
					</button>
					<button class="btn btn-ghost btn-sm" onclick={() => videoStore.seek(videoStore.outPoint)}>
						Jump to out
					</button>
				</div>

				<div class="panel timeline-panel">
					<Timeline />
				</div>

				{#if !isolated}
					<p class="notice" data-tone="warn">
						This page is not cross-origin isolated, so SharedArrayBuffer is unavailable and the
						multithreaded core cannot start. Run the app through <code>npm run dev</code> (or the
						Node build) so the COOP/COEP headers are applied.
					</p>
				{/if}
			</section>

			<aside class="panel controls">
				<div class="panel-head">
					<h2>Clip settings</h2>
					<span class="mono muted small">{videoStore.trimLength.toFixed(2)}s</span>
				</div>

				<div class="panel-body">
					<div>
						<span class="label">Trim range</span>
						<div class="fields">
							<label class="field">
								<input
									type="number"
									min="0"
									max={videoStore.duration}
									step="0.05"
									value={videoStore.inPoint.toFixed(2)}
									onchange={(event) =>
										videoStore.setIn(Number((event.currentTarget as HTMLInputElement).value))}
								/>
								<span class="unit">in</span>
							</label>
							<label class="field">
								<input
									type="number"
									min="0"
									max={videoStore.duration}
									step="0.05"
									value={videoStore.outPoint.toFixed(2)}
									onchange={(event) =>
										videoStore.setOut(Number((event.currentTarget as HTMLInputElement).value))}
								/>
								<span class="unit">out</span>
							</label>
						</div>
						<div class="quick">
							<button class="btn btn-ghost btn-sm" onclick={setInFromPlayhead}>in @ playhead</button>
							<button class="btn btn-ghost btn-sm" onclick={setOutFromPlayhead}>out @ playhead</button>
						</div>
					</div>

					<div>
						<div class="section-head">
							<span class="label">Send to</span>
							<span class="mono tiny muted">
								{targets.selected.length}/{indiePost.connected.length} selected
							</span>
						</div>
						<AccountTargets />
						{#if indiePost.loaded && indiePost.connected.length > 0 && targets.selected.length === 0}
							<p class="muted tiny">Nothing ticked — this render will just download.</p>
						{/if}
					</div>

					<div>
						<div class="section-head">
							<span class="label">Frame</span>
							<label class="auto-frame">
								<input
									type="checkbox"
									checked={targets.autoFrame}
									onchange={(event) =>
										targets.setAutoFrame((event.currentTarget as HTMLInputElement).checked)}
								/>
								<span>Auto from platforms</span>
								{#if targets.autoFrame && targets.recommendedAspect}
									<span class="mono tiny">{targets.recommendedAspect}</span>
								{/if}
							</label>
						</div>
						<div class="chips">
							{#each ASPECTS as preset (preset.id)}
								<button
									class="chip"
									aria-pressed={videoStore.aspect === preset.id}
									onclick={() => {
										videoStore.aspect = preset.id;
										if (preset.id !== targets.recommendedAspect) targets.setAutoFrame(false);
									}}
								>
									<strong>{preset.label}</strong>
									<span>{preset.hint}</span>
								</button>
							{/each}
						</div>
					</div>

					<div>
						<span class="label">Look</span>
						<div class="chips">
							{#each LOOKS as preset (preset.id)}
								<button
									class="chip"
									aria-pressed={videoStore.look === preset.id}
									onclick={() => (videoStore.look = preset.id)}
								>
									<strong>{preset.label}</strong>
									<span>{preset.hint}</span>
								</button>
							{/each}
						</div>
					</div>

					<div class="render">
						<button
							class="btn btn-primary btn-wide"
							onclick={exportClip}
							disabled={!videoStore.canExport}
						>
							{rendering ? `Rendering ${Math.round(rendering.progress * 100)}%` : 'Render clip'}
						</button>

						{#if rendering}
							<div class="progress"><span style="width: {rendering.progress * 100}%"></span></div>
							<p class="render-note mono">
								{rendering.progress * 100}% · worker thread
								{#if queued > 0} · {queued} queued{/if}
							</p>
						{:else if queued > 0}
							<p class="render-note mono">{queued} queued</p>
						{:else}
							<p class="render-note mono">H.264 · MP4 · 1080p target</p>
						{/if}
					</div>

					{#if justRendered}
						<div class="done">
							<p>Rendered. Write metadata and publish it from Exports.</p>
							<a class="btn btn-sm" href="/exports">Open exports</a>
						</div>
					{/if}

					{#if errorMessage}
						<p class="notice">{errorMessage}</p>
					{/if}
				</div>
			</aside>
		</div>
	{/if}
</div>

<style>
	.blank {
		display: flex;
		flex-direction: column;
		gap: 22px;
		max-width: 720px;
		padding-block: 28px;
	}

	.blank h1 {
		margin-top: 12px;
		margin-bottom: 8px;
		font-size: clamp(1.7rem, 3.6vw, 2.4rem);
	}

	.workspace {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 336px;
		gap: 16px;
		align-items: start;
	}

	.stage-col {
		display: flex;
		flex-direction: column;
		gap: 12px;
		min-width: 0;
	}

	.stage-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	.file {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.file strong {
		overflow: hidden;
		font-size: 14px;
		font-weight: 600;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.file span {
		font-size: 11.5px;
	}

	.stage {
		position: relative;
		display: block;
		overflow: hidden;
		border: 1px solid var(--line);
		border-radius: var(--radius);
		background: #000;
	}

	.stage video {
		display: block;
		width: 100%;
		max-height: 58vh;
		background: #000;
		object-fit: contain;
	}

	.stage :global(.overlay) {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
	}

	.badge {
		position: absolute;
		bottom: 10px;
		left: 10px;
		padding: 4px 9px;
		border: 1px solid rgba(255, 255, 255, 0.14);
		border-radius: 7px;
		background: rgba(6, 7, 9, 0.72);
		font-size: 12px;
		backdrop-filter: blur(6px);
	}

	.badge .dim {
		color: var(--muted);
	}

	.transport {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
	}

	.spacer {
		flex: 1 1 auto;
	}

	.timeline-panel {
		padding: 14px 16px 10px;
	}

	.controls {
		position: sticky;
		top: 76px;
	}

	.small {
		font-size: 11.5px;
	}

	.tiny {
		font-size: 10.5px;
	}

	.section-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 8px;
		margin-bottom: 10px;
	}

	.section-head .label {
		margin-bottom: 0;
	}

	.auto-frame {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		color: var(--muted);
		font-size: 11px;
		cursor: pointer;
	}

	.auto-frame input {
		accent-color: var(--accent);
	}

	.fields {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
		margin-bottom: 8px;
	}

	.quick {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
	}

	.render {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding-top: 4px;
	}

	.render-note {
		color: var(--muted);
		font-size: 11px;
		letter-spacing: 0.04em;
		text-align: center;
	}

	.done {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		padding: 10px 12px;
		border: 1px solid rgba(98, 224, 160, 0.3);
		border-radius: var(--radius-sm);
		background: rgba(98, 224, 160, 0.08);
		font-size: 13px;
		color: #b8f3d6;
	}

	code {
		font-family: var(--mono);
	}

	input[type='number'] {
		appearance: textfield;
		-moz-appearance: textfield;
	}

	input[type='number']::-webkit-outer-spin-button,
	input[type='number']::-webkit-inner-spin-button {
		margin: 0;
		appearance: none;
	}

	@media (max-width: 980px) {
		.workspace {
			grid-template-columns: minmax(0, 1fr);
		}

		.controls {
			position: static;
		}
	}
</style>
