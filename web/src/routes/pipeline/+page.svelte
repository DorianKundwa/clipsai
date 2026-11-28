<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { videoStore } from '#lib/stores/videoStore.svelte';
	import { formatBytes, type Aspect } from '#lib/video';

	interface StageOption {
		stage: string;
		label: string;
		enabled: boolean;
		done: boolean;
		reason: string;
	}

	interface DiscoveredClip {
		index: number;
		selected: boolean;
		start_time: number;
		end_time: number;
		duration: number;
		score: number;
		hook: string;
		title: string;
		reason: string;
		text: string;
	}

	interface VideoArtifact {
		index: number;
		name: string;
		url: string;
		size: number;
	}

	interface CaptionArtifact {
		index: number | null;
		name: string;
		video_url: string | null;
		srt_url: string | null;
		size: number;
	}

	interface PackageArtifact {
		index: number;
		hook: string;
		title: string;
		hooked_url: string | null;
		thumbnail_url: string | null;
		effects_url: string | null;
		package_url: string | null;
	}

	interface JobState {
		job_id: string;
		created: string;
		updated: string;
		config: Record<string, unknown>;
		completed: string[];
		next_options: StageOption[];
		next_stage: string;
		clips: DiscoveredClip[];
		artifacts: {
			source_url: string | null;
			source_name: string;
			transcript_url: string | null;
			clips_url: string | null;
			trimmed: VideoArtifact[];
			reframed: VideoArtifact[];
			captions: CaptionArtifact[];
			packages: PackageArtifact[];
			final: VideoArtifact[];
			published: Array<Record<string, unknown>>;
		};
		running: boolean;
		progress: {
			stage: string;
			fraction: number;
			message: string;
		};
		last_result: {
			stage?: string;
			ok?: boolean;
			message?: string;
			error?: string;
		} | null;
	}

	interface ServicesState {
		deepseek?: { configured?: boolean; model?: string };
		huggingface?: { configured?: boolean };
		indiepost?: { configured?: boolean };
		env?: { ffmpeg?: string | null; python?: string };
	}

	interface OptionsState {
		model_sizes: string[];
		devices: string[];
		languages: string[];
		selection_methods: Array<{ id: string; label: string }>;
		cutoff_policies: string[];
		aspect_ratios: string[];
		caption_styles: string[];
		caption_positions: string[];
		fonts: Array<{ key: string; label: string; family: string }>;
		hook_styles: string[];
		hook_positions: string[];
		export_profiles: Array<{ key: string; label: string }>;
		grades: string[];
		pad_modes: string[];
		ai_languages: string[];
		platforms: string[];
		tiktok_privacy: string[];
		youtube_formats: string[];
	}

	const DEFAULT_OPTIONS: OptionsState = {
		model_sizes: ['auto', 'tiny', 'base', 'small', 'medium', 'large-v1', 'large-v2'],
		devices: ['auto', 'cpu', 'cuda'],
		languages: ['auto', 'en', 'fr', 'de', 'es', 'it', 'ja', 'zh', 'nl', 'uk', 'pt'],
		selection_methods: [
			{ id: 'texttiling', label: 'TextTiling (fast, local)' },
			{ id: 'deepseek', label: 'DeepSeek AI' }
		],
		cutoff_policies: ['high', 'average', 'low'],
		aspect_ratios: ['9:16', '3:4', '4:5', '1:1', '16:9'],
		caption_styles: [
			'bold',
			'kinetic',
			'shorts',
			'clean',
			'lime',
			'pill',
			'boxed',
			'impact',
			'editorial',
			'oneword'
		],
		caption_positions: ['bottom', 'center', 'top'],
		fonts: [
			{ key: 'montserrat-extrabold', label: 'Montserrat ExtraBold', family: 'Montserrat ExtraBold' },
			{ key: 'archivo-black', label: 'Archivo Black', family: 'Archivo Black' },
			{ key: 'noto-serif', label: 'Noto Serif Bold', family: 'Noto Serif' }
		],
		hook_styles: ['card', 'box', 'dark', 'yellow', 'outline'],
		hook_positions: ['top', 'upper', 'center', 'lower', 'bottom'],
		export_profiles: [
			{ key: 'off', label: 'Off — keep the current render' },
			{ key: 'shorts', label: 'YouTube Shorts — 1080×1920 · 60 fps · 12 Mbps' },
			{ key: 'reels', label: 'Instagram Reels — 1080×1920 · 30 fps · 10 Mbps' },
			{ key: 'tiktok', label: 'TikTok — 1080×1920 · 30 fps · 10 Mbps' },
			{ key: 'youtube', label: 'YouTube — 1920×1080 · 30 fps · 12 Mbps' },
			{ key: 'square', label: 'Square feed — 1080×1080 · 30 fps · 8 Mbps' }
		],
		grades: ['none', 'warm', 'cool', 'punchy', 'film', 'mono'],
		pad_modes: ['blur', 'crop', 'black'],
		ai_languages: ['off', 'en', 'es', 'fr', 'de', 'pt', 'it', 'nl', 'ja', 'ko', 'zh'],
		platforms: ['youtube', 'tiktok', 'instagram', 'facebook'],
		tiktok_privacy: [
			'PUBLIC_TO_EVERYONE',
			'MUTUAL_FOLLOW_FRIENDS',
			'FOLLOWER_OF_CREATOR',
			'SELF_ONLY'
		],
		youtube_formats: ['short', 'long']
	};

	let options = $state<OptionsState>(DEFAULT_OPTIONS);
	let services = $state<ServicesState | null>(null);
	let servicesLoading = $state(false);

	let videoFile = $state<File | null>(null);
	let transcriptFile = $state<File | null>(null);

	let modelSize = $state('auto');
	let language = $state('auto');
	let device = $state('auto');
	let method = $state('texttiling');
	let minDuration = $state(15);
	let maxDuration = $state(60);
	let topN = $state(3);
	let cutoffPolicy = $state('high');
	let aspectRatio = $state('9:16');
	let renderVertical = $state(true);
	let keepTrimmed = $state(true);
	let captions = $state(false);
	let captionPreset = $state('bold');
	let captionFont = $state('montserrat-extrabold');
	let captionSize = $state(0);
	let captionPosition = $state('bottom');
	let captionPop = $state(false);
	let translateTo = $state('off');
	let exportProfile = $state('off');
	let grade = $state('none');
	let punchIns = $state(false);
	let sourceCrop = $state('');
	let hookStyle = $state('card');
	let hookPosition = $state('upper');
	let hookFont = $state('montserrat-extrabold');
	let hookKicker = $state('');
	let hookSeconds = $state(4);
	let packageAi = $state(false);
	let hook = $state(false);
	let thumbnail = $state(false);
	let effects = $state(false);
	let publish = $state(false);
	let selectedPlatforms = $state<string[]>(['instagram']);
	let publishCaption = $state('');
	let youtubeTitle = $state('');
	let youtubeFormat = $state<'short' | 'long'>('short');
	let tiktokPrivacy = $state('PUBLIC_TO_EVERYONE');
	let aiGenerated = $state(false);
	let publishWhen = $state('now');

	let job = $state<JobState | null>(null);
	let selectedStage = $state('transcribe');
	let busyUpload = $state(false);
	let transferringUrl = $state<string | null>(null);
	let errorMessage = $state<string | null>(null);

	let eventSource: EventSource | null = null;
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	const enabledStages = $derived(
		job ? job.next_options.filter((opt) => opt.enabled) : []
	);

	function buildConfigPayload(): Record<string, unknown> {
		return {
			model_size: modelSize,
			language,
			device,
			method,
			min_clip_duration: Number(minDuration),
			max_clip_duration: Number(maxDuration),
			top_n: Number(topN),
			cutoff_policy: cutoffPolicy,
			aspect_ratio: aspectRatio,
			render_vertical: renderVertical,
			keep_trimmed: keepTrimmed,
			captions,
			caption_preset: captionPreset,
			font: captionFont,
			caption_size: Number(captionSize),
			caption_position: captionPosition,
			caption_pop: captionPop,
			translate_to: translateTo,
			export_profile: exportProfile,
			grade,
			punch_ins: punchIns,
			source_crop: sourceCrop,
			hook_style: hookStyle,
			hook_position: hookPosition,
			hook_kicker: hookKicker,
			hook_font: hookFont,
			hook_seconds: Number(hookSeconds),
			package: packageAi,
			hook,
			thumbnail,
			effects,
			publish,
			platforms: selectedPlatforms,
			publish_caption: publishCaption,
			youtube_title: youtubeTitle,
			youtube_format: youtubeFormat,
			tiktok_privacy: tiktokPrivacy,
			ai_generated: aiGenerated,
			when: publishWhen
		};
	}

	function applyJobState(nextJob: JobState): void {
		job = nextJob;
		const enabled = nextJob.next_options.filter((opt) => opt.enabled);
		if (enabled.length > 0 && !enabled.some((opt) => opt.stage === selectedStage)) {
			selectedStage = enabled[0].stage;
		} else if (enabled.length === 0) {
			selectedStage = '';
		}
	}

	async function loadServicesAndOptions(): Promise<void> {
		servicesLoading = true;
		try {
			const [svcRes, optRes] = await Promise.all([
				fetch('/api/services'),
				fetch('/api/pipeline/options')
			]);
			if (svcRes.ok) services = await svcRes.json();
			if (optRes.ok) options = await optRes.json();
		} catch {
			errorMessage = 'Could not reach the ClipsAI backend.';
		} finally {
			servicesLoading = false;
		}
	}

	function stopStreaming(): void {
		if (eventSource) {
			eventSource.close();
			eventSource = null;
		}
		if (pollTimer) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	}

	function startStreaming(jobId: string): void {
		stopStreaming();

		const es = new EventSource(`/api/pipeline/jobs/${encodeURIComponent(jobId)}/events`);
		eventSource = es;

		es.onmessage = (event) => {
			try {
				const data = JSON.parse(event.data);
				if (data.type === 'snapshot' && data.job) {
					applyJobState(data.job as JobState);
				} else if (data.type === 'progress' && data.progress && job) {
					job = {
						...job,
						running: Boolean(data.progress.running ?? true),
						progress: {
							stage: String(data.progress.stage ?? job.progress.stage),
							fraction: Number(data.progress.fraction ?? job.progress.fraction),
							message: String(data.progress.message ?? job.progress.message)
						}
					};
				} else if (data.type === 'done' && data.job) {
					applyJobState(data.job as JobState);
					stopStreaming();
				}
			} catch {
				// Ignore malformed keepalive frames.
			}
		};

		es.onerror = () => {
			es.close();
			eventSource = null;
			if (!pollTimer) {
				pollTimer = setInterval(async () => {
					try {
						const res = await fetch(`/api/pipeline/jobs/${encodeURIComponent(jobId)}`);
						if (!res.ok) return;
						const updated = (await res.json()) as JobState;
						applyJobState(updated);
						if (!updated.running) stopStreaming();
					} catch {
						// Wait for next tick.
					}
				}, 1500);
			}
		};
	}

	async function ensureJob(): Promise<JobState | null> {
		const config = buildConfigPayload();
		if (job) {
			const res = await fetch(`/api/pipeline/jobs/${encodeURIComponent(job.job_id)}/config`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(config)
			});
			const data = await res.json().catch(() => ({}));
			if (!res.ok) throw new Error(data.error ?? `Failed to save settings (HTTP ${res.status}).`);
			applyJobState(data as JobState);
			return data as JobState;
		}

		if (!videoFile && !transcriptFile) {
			throw new Error('Select a video file or an existing transcript JSON first.');
		}

		busyUpload = true;
		try {
			const form = new FormData();
			form.set('config', JSON.stringify(config));
			if (videoFile) form.set('video', videoFile, videoFile.name);
			if (transcriptFile) form.set('transcript', transcriptFile, transcriptFile.name);

			const res = await fetch('/api/pipeline/jobs', {
				method: 'POST',
				body: form
			});
			const data = await res.json().catch(() => ({}));
			if (!res.ok) throw new Error(data.error ?? `Could not create job (HTTP ${res.status}).`);
			applyJobState(data as JobState);
			return data as JobState;
		} finally {
			busyUpload = false;
		}
	}

	async function runStage(stageOverride?: string): Promise<void> {
		errorMessage = null;
		try {
			const active = await ensureJob();
			if (!active) return;
			const stage = stageOverride || selectedStage || active.next_stage;
			if (!stage) return;

			const res = await fetch(`/api/pipeline/jobs/${encodeURIComponent(active.job_id)}/run`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ stage, config: buildConfigPayload() })
			});
			const data = await res.json().catch(() => ({}));
			if (!res.ok) throw new Error(data.error ?? `Could not start ${stage} (HTTP ${res.status}).`);
			applyJobState(data as JobState);
			if ((data as JobState).running) startStreaming(active.job_id);
		} catch (problem) {
			errorMessage = problem instanceof Error ? problem.message : 'Pipeline stage failed.';
		}
	}

	async function runAll(): Promise<void> {
		errorMessage = null;
		try {
			const active = await ensureJob();
			if (!active) return;

			const res = await fetch(`/api/pipeline/jobs/${encodeURIComponent(active.job_id)}/run-all`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ config: buildConfigPayload() })
			});
			const data = await res.json().catch(() => ({}));
			if (!res.ok) throw new Error(data.error ?? `Pipeline failed (HTTP ${res.status}).`);
			applyJobState(data as JobState);
			if ((data as JobState).running) startStreaming(active.job_id);
		} catch (problem) {
			errorMessage = problem instanceof Error ? problem.message : 'Pipeline failed.';
		}
	}

	function newJob(): void {
		stopStreaming();
		job = null;
		selectedStage = 'transcribe';
		errorMessage = null;
	}

	function togglePlatform(name: string): void {
		if (selectedPlatforms.includes(name)) {
			selectedPlatforms = selectedPlatforms.filter((p) => p !== name);
		} else {
			selectedPlatforms = [...selectedPlatforms, name];
		}
	}

	function replaceFiles(): void {
		newJob();
	}

	function mappedAspect(): Aspect {
		if (aspectRatio === '9:16' || aspectRatio === '1:1' || aspectRatio === '16:9') {
			return aspectRatio;
		}
		return 'source';
	}

	async function openInStudio(url: string, name: string, range?: { start?: number; end?: number }): Promise<void> {
		transferringUrl = url;
		errorMessage = null;
		try {
			await videoStore.attachFromUrl(url, name, range);
			await goto('/studio');
		} catch (problem) {
			errorMessage = problem instanceof Error ? problem.message : 'Could not load clip in Studio.';
		} finally {
			transferringUrl = null;
		}
	}

	async function sendToExports(url: string, label: string, fileName: string): Promise<void> {
		transferringUrl = url;
		errorMessage = null;
		try {
			await videoStore.importExportFromUrl(url, label, fileName, { aspect: mappedAspect() });
			await goto('/exports');
		} catch (problem) {
			errorMessage = problem instanceof Error ? problem.message : 'Could not add clip to Exports.';
		} finally {
			transferringUrl = null;
		}
	}

	onMount(() => {
		void loadServicesAndOptions();
	});

	onDestroy(stopStreaming);
</script>

<svelte:head>
	<title>Pipeline — ClipsAI</title>
</svelte:head>

<div class="page">
	<header class="head">
		<div>
			<span class="eyebrow">WhisperX · TextTiling / DeepSeek · Pyannote</span>
			<h1>Auto AI Pipeline</h1>
			<p class="muted">
				Transcribe a long video, discover top moments, apply speaker-tracking 9:16 reframe,
				burn captions, or hand any cut over to Studio and Exports.
			</p>
		</div>
		<div class="services">
			{#if services}
				<span class="pill" data-status={services.deepseek?.configured ? 'done' : 'error'}>
					DeepSeek {services.deepseek?.configured ? 'ready' : 'missing'}
				</span>
				<span class="pill" data-status={services.huggingface?.configured ? 'done' : 'error'}>
					HF / Pyannote {services.huggingface?.configured ? 'ready' : 'missing'}
				</span>
				<span class="pill" data-status={services.indiepost?.configured ? 'done' : 'error'}>
					IndiePost {services.indiepost?.configured ? 'ready' : 'missing'}
				</span>
				<span class="pill" data-status={services.env?.ffmpeg ? 'done' : 'error'}>
					ffmpeg {services.env?.ffmpeg ? 'ready' : 'missing'}
				</span>
			{/if}
			<button class="btn btn-ghost btn-sm" onclick={loadServicesAndOptions} disabled={servicesLoading}>
				{servicesLoading ? 'Checking…' : 'Refresh status'}
			</button>
		</div>
	</header>

	<div class="grid">
		<section class="sidebar">
			<div class="panel">
				<div class="panel-head">
					<h2>1. Source & transcription</h2>
				</div>
				<div class="panel-body">
					<label class="stack">
						<span class="label">Video file</span>
						<input
							class="file-input"
							type="file"
							accept="video/*,audio/*"
							onchange={(event) => {
								const files = (event.currentTarget as HTMLInputElement).files;
								videoFile = files?.[0] ?? null;
								replaceFiles();
							}}
						/>
						{#if videoFile}
							<span class="mono tiny muted">{videoFile.name} · {formatBytes(videoFile.size)}</span>
						{/if}
					</label>

					<label class="stack">
						<span class="label">Existing transcript JSON (optional)</span>
						<input
							class="file-input"
							type="file"
							accept=".json,application/json"
							onchange={(event) => {
								const files = (event.currentTarget as HTMLInputElement).files;
								transcriptFile = files?.[0] ?? null;
								replaceFiles();
							}}
						/>
						{#if transcriptFile}
							<span class="mono tiny muted">{transcriptFile.name}</span>
						{/if}
					</label>

					<div class="row-2">
						<label class="stack">
							<span class="label">Whisper model</span>
							<select class="select" bind:value={modelSize}>
								{#each options.model_sizes as size (size)}
									<option value={size}>{size}</option>
								{/each}
							</select>
						</label>
						<label class="stack">
							<span class="label">Language</span>
							<select class="select" bind:value={language}>
								{#each options.languages as lang (lang)}
									<option value={lang}>{lang}</option>
								{/each}
							</select>
						</label>
					</div>

					<label class="stack">
						<span class="label">Device</span>
						<select class="select" bind:value={device}>
							{#each options.devices as dev (dev)}
								<option value={dev}>{dev}</option>
							{/each}
						</select>
					</label>
				</div>
			</div>

			<div class="panel">
				<div class="panel-head">
					<h2>2. Clip selection</h2>
				</div>
				<div class="panel-body">
					<div class="chips">
						{#each options.selection_methods as item (item.id)}
							<button
								type="button"
								class="chip"
								aria-pressed={method === item.id}
								onclick={() => (method = item.id)}
							>
								<strong>{item.id === 'deepseek' ? 'DeepSeek AI' : 'TextTiling'}</strong>
								<span>{item.id === 'deepseek' ? 'Scored hooks & titles' : 'Fast local embeddings'}</span>
							</button>
						{/each}
					</div>

					<div class="row-3">
						<label class="stack">
							<span class="label">Min (s)</span>
							<div class="field"><input type="number" min="5" max="600" bind:value={minDuration} /></div>
						</label>
						<label class="stack">
							<span class="label">Max (s)</span>
							<div class="field"><input type="number" min="10" max="1800" bind:value={maxDuration} /></div>
						</label>
						<label class="stack">
							<span class="label">Top clips</span>
							<div class="field"><input type="number" min="1" max="20" bind:value={topN} /></div>
						</label>
					</div>

					<label class="stack">
						<span class="label">TextTiling cutoff</span>
						<select class="select" bind:value={cutoffPolicy}>
							{#each options.cutoff_policies as policy (policy)}
								<option value={policy}>{policy}</option>
							{/each}
						</select>
					</label>
				</div>
			</div>

			<div class="panel">
				<div class="panel-head">
					<h2>3. Output & captions</h2>
				</div>
				<div class="panel-body">
					<label class="stack">
						<span class="label">Aspect ratio</span>
						<select class="select" bind:value={aspectRatio}>
							{#each options.aspect_ratios as ratio (ratio)}
								<option value={ratio}>{ratio}</option>
							{/each}
						</select>
					</label>

					<label class="check">
						<input type="checkbox" bind:checked={renderVertical} />
						<span>Reframe to speaker-tracked vertical</span>
					</label>
					<label class="check">
						<input type="checkbox" bind:checked={keepTrimmed} />
						<span>Keep trimmed (original aspect) clips</span>
					</label>
					<label class="check">
						<input type="checkbox" bind:checked={captions} />
						<span>Burn animated word-timed captions</span>
					</label>

					{#if captions}
						<div class="row-2">
							<label class="stack">
								<span class="label">Style</span>
								<select class="select" bind:value={captionPreset}>
									{#each options.caption_styles as style (style)}
										<option value={style}>{style}</option>
									{/each}
								</select>
							</label>
							<label class="stack">
								<span class="label">Translate (AI)</span>
								<select class="select" bind:value={translateTo}>
									{#each options.ai_languages as lang (lang)}
										<option value={lang}>{lang}</option>
									{/each}
								</select>
							</label>
						</div>
						<div class="row-2">
							<label class="stack">
								<span class="label">Font</span>
								<select class="select" bind:value={captionFont}>
									{#each options.fonts as face (face.key)}
										<option value={face.key}>{face.label}</option>
									{/each}
								</select>
							</label>
							<label class="stack">
								<span class="label">Position</span>
								<select class="select" bind:value={captionPosition}>
									{#each options.caption_positions as position (position)}
										<option value={position}>{position}</option>
									{/each}
								</select>
							</label>
						</div>
						<div class="row-2">
							<label class="stack">
								<span class="label">Font size px (0 = preset)</span>
								<div class="field"><input type="number" min="0" max="200" bind:value={captionSize} /></div>
							</label>
							<label class="check">
								<input type="checkbox" bind:checked={captionPop} />
								<span>Pop the spoken word</span>
							</label>
						</div>
					{/if}

					<hr class="sep-line" />

					<div class="row-2">
						<label class="stack">
							<span class="label">Master export profile</span>
							<select class="select" bind:value={exportProfile}>
								{#each options.export_profiles as profile (profile.key)}
									<option value={profile.key}>{profile.label}</option>
								{/each}
							</select>
						</label>
						<label class="stack">
							<span class="label">Colour grade</span>
							<select class="select" bind:value={grade}>
								{#each options.grades as item (item)}
									<option value={item}>{item}</option>
								{/each}
							</select>
						</label>
					</div>
					<label class="check">
						<input type="checkbox" bind:checked={punchIns} />
						<span>Punch-in cadence (102% → 108%)</span>
					</label>
					<label class="stack">
						<span class="label">Source crop — top,bottom,left,right fractions</span>
						<input class="text-input" type="text" bind:value={sourceCrop} placeholder="0,0.28,0,0 removes a burned-in caption strip" />
					</label>
				</div>
			</div>

			<details class="panel">
				<summary class="panel-head summary-head">
					<h2>4. Packaging & IndiePost</h2>
					<span class="mono tiny muted">Optional</span>
				</summary>
				<div class="panel-body">
					<label class="check">
						<input type="checkbox" bind:checked={packageAi} />
						<span>Generate AI packaging (hook, titles, metadata)</span>
					</label>
					<label class="check">
						<input type="checkbox" bind:checked={hook} />
						<span>Burn the opening hook card</span>
					</label>
					{#if hook}
						<div class="row-2">
							<label class="stack">
								<span class="label">Hook style</span>
								<select class="select" bind:value={hookStyle}>
									{#each options.hook_styles as style (style)}
										<option value={style}>{style}</option>
									{/each}
								</select>
							</label>
							<label class="stack">
								<span class="label">Position</span>
								<select class="select" bind:value={hookPosition}>
									{#each options.hook_positions as position (position)}
										<option value={position}>{position}</option>
									{/each}
								</select>
							</label>
						</div>
						<div class="row-2">
							<label class="stack">
								<span class="label">Hook font</span>
								<select class="select" bind:value={hookFont}>
									{#each options.fonts as face (face.key)}
										<option value={face.key}>{face.label}</option>
									{/each}
								</select>
							</label>
							<label class="stack">
								<span class="label">On screen (s)</span>
								<div class="field"><input type="number" min="0.5" max="60" step="0.5" bind:value={hookSeconds} /></div>
							</label>
						</div>
						<label class="stack">
							<span class="label">Kicker (optional question above the hook)</span>
							<input class="text-input" type="text" bind:value={hookKicker} />
						</label>
					{/if}
					<label class="check">
						<input type="checkbox" bind:checked={thumbnail} />
						<span>Create 1280×720 thumbnail</span>
					</label>
					<label class="check">
						<input type="checkbox" bind:checked={effects} />
						<span>Apply AI video effects</span>
					</label>

					<hr class="sep-line" />

					<label class="check">
						<input type="checkbox" bind:checked={publish} />
						<span>Auto-publish finished clips with IndiePost</span>
					</label>

					{#if publish}
						<div>
							<span class="label">Platforms</span>
							<div class="plat-row">
								{#each options.platforms as platform (platform)}
									<button
										type="button"
										class="btn btn-sm"
										class:btn-primary={selectedPlatforms.includes(platform)}
										onclick={() => togglePlatform(platform)}
									>
										{platform}
									</button>
								{/each}
							</div>
						</div>
						<label class="stack">
							<span class="label">Caption override (blank = from packaging/text)</span>
							<input class="text-input" type="text" bind:value={publishCaption} />
						</label>
						<label class="stack">
							<span class="label">YouTube title (blank = from packaging)</span>
							<input class="text-input" type="text" bind:value={youtubeTitle} />
						</label>
						<div class="row-2">
							<label class="stack">
								<span class="label">YouTube format</span>
								<select class="select" bind:value={youtubeFormat}>
									<option value="short">short</option>
									<option value="long">long</option>
								</select>
							</label>
							<label class="stack">
								<span class="label">TikTok privacy</span>
								<select class="select" bind:value={tiktokPrivacy}>
									{#each options.tiktok_privacy as level (level)}
										<option value={level}>{level}</option>
									{/each}
								</select>
							</label>
						</div>
						<label class="check">
							<input type="checkbox" bind:checked={aiGenerated} />
							<span>Label as AI-generated</span>
						</label>
						<label class="stack">
							<span class="label">Publish time ('now' or ISO timestamp)</span>
							<input class="text-input" type="text" bind:value={publishWhen} />
						</label>
					{/if}
				</div>
			</details>
		</section>

		<section class="workspace">
			<div class="panel">
				<div class="panel-head">
					<div>
						<h2>Pipeline execution</h2>
						<p class="mono tiny muted">
							{#if job}
								Job {job.job_id} · {job.completed.length} stage(s) done
							{:else}
								Ready to start
							{/if}
						</p>
					</div>
					<div class="btn-row">
						<button
							class="btn btn-primary btn-sm"
							onclick={() => runStage()}
							disabled={busyUpload || job?.running || (!!job && enabledStages.length === 0)}
						>
							{busyUpload ? 'Uploading…' : 'Run next step'}
						</button>
						<button
							class="btn btn-sm"
							onclick={runAll}
							disabled={busyUpload || job?.running}
						>
							Run all enabled stages
						</button>
						<button class="btn btn-ghost btn-sm" onclick={newJob} disabled={busyUpload || job?.running}>
							New job
						</button>
					</div>
				</div>

				<div class="panel-body">
					{#if job}
						<div class="stage-strip">
							{#each job.next_options as opt (opt.stage)}
								<button
									type="button"
									class="stage-pill"
									data-done={opt.done}
									data-selected={selectedStage === opt.stage}
									disabled={!opt.enabled || job.running}
									title={opt.reason || opt.label}
									onclick={() => (selectedStage = opt.stage)}
								>
									{#if opt.done}✓ {/if}{opt.label}
								</button>
							{/each}
						</div>

						{#if job.running}
							<div class="progress">
								<span style="width: {Math.round((job.progress.fraction || 0) * 100)}%"></span>
							</div>
							<p class="mono small muted">
								Running {job.progress.stage || 'stage'} · {Math.round((job.progress.fraction || 0) * 100)}%
								{#if job.progress.message} · {job.progress.message}{/if}
							</p>
						{:else if job.last_result}
							{#if job.last_result.ok}
								<p class="notice ok-notice">{job.last_result.message}</p>
							{:else if job.last_result.error}
								<p class="notice">{job.last_result.error}</p>
							{/if}
						{/if}
					{:else}
						<p class="muted small">
							Select a video (or transcript JSON) on the left and press <strong>Run next step</strong>
							to run stage-by-stage, or <strong>Run all enabled stages</strong> to process automatically.
						</p>
					{/if}

					{#if errorMessage}
						<p class="notice">{errorMessage}</p>
					{/if}
				</div>
			</div>

			{#if job && job.clips.length > 0}
				<div class="panel">
					<div class="panel-head">
						<h2>Discovered clips</h2>
						<span class="mono tiny muted">{job.clips.length} found</span>
					</div>
					<div class="panel-body clip-list">
						{#each job.clips as clip (clip.index)}
							<article class="clip-card" data-selected={clip.selected}>
								<div class="clip-top">
									<div class="clip-meta">
										<strong>#{clip.index + 1}</strong>
										<span class="mono small">
											{clip.start_time}s → {clip.end_time}s ({clip.duration}s)
										</span>
										{#if clip.score > 0}
											<span class="pill" data-status="done">score {clip.score}</span>
										{/if}
										{#if clip.selected}
											<span class="pill" data-status="rendering">selected</span>
										{/if}
									</div>
									{#if job.artifacts.source_url}
										<button
											class="btn btn-ghost btn-sm"
											disabled={transferringUrl !== null}
											onclick={() =>
												openInStudio(
													job!.artifacts.source_url!,
													job!.artifacts.source_name || 'source.mp4',
													{ start: clip.start_time, end: clip.end_time }
												)}
										>
											Open range in Studio
										</button>
									{/if}
								</div>
								{#if clip.hook || clip.title}
									<p class="clip-title">{clip.hook || clip.title}</p>
								{/if}
								{#if clip.text}
									<p class="muted small">{clip.text}</p>
								{/if}
							</article>
						{/each}
					</div>
				</div>
			{/if}

			{#if job && (job.artifacts.trimmed.length > 0 || job.artifacts.reframed.length > 0 || job.artifacts.captions.length > 0 || job.artifacts.final.length > 0 || job.artifacts.packages.length > 0 || job.artifacts.published.length > 0)}
				<div class="panel">
					<div class="panel-head">
						<h2>Rendered clips & artifacts</h2>
						{#if job.artifacts.transcript_url}
							<a class="btn btn-ghost btn-sm" href={job.artifacts.transcript_url} download="transcript.json">
								Download transcript JSON
							</a>
						{/if}
					</div>
					<div class="panel-body artifact-grid">
						{#each [...job.artifacts.final.map((a) => ({ ...a, tag: 'Master export' })), ...job.artifacts.reframed.map((a) => ({ ...a, tag: 'Vertical reframe' })), ...job.artifacts.trimmed.map((a) => ({ ...a, tag: 'Trimmed clip' }))] as item (item.url)}
							<article class="artifact-card">
								<div class="artifact-head">
									<div>
										<span class="pill" data-status="done">{item.tag}</span>
										<strong class="mono small">{item.name}</strong>
									</div>
									<span class="mono tiny muted">{formatBytes(item.size)}</span>
								</div>
								<!-- svelte-ignore a11y_media_has_caption -->
								<video controls preload="metadata" src={item.url}></video>
								<div class="btn-row">
									<a class="btn btn-sm" href={item.url} download={item.name}>Download</a>
									<button
										class="btn btn-sm"
										disabled={transferringUrl !== null}
										onclick={() => openInStudio(item.url, item.name)}
									>
										{transferringUrl === item.url ? 'Opening…' : 'Edit in Studio'}
									</button>
									<button
										class="btn btn-primary btn-sm"
										disabled={transferringUrl !== null}
										onclick={() => sendToExports(item.url, item.name, item.name)}
									>
										Send to Exports
									</button>
								</div>
							</article>
						{/each}

						{#each job.artifacts.captions as cap (cap.srt_url ?? cap.video_url ?? cap.name)}
							{#if cap.video_url}
								<article class="artifact-card">
									<div class="artifact-head">
										<div>
											<span class="pill" data-status="done">Captioned</span>
											<strong class="mono small">{cap.name}</strong>
										</div>
										<span class="mono tiny muted">{formatBytes(cap.size)}</span>
									</div>
									<!-- svelte-ignore a11y_media_has_caption -->
									<video controls preload="metadata" src={cap.video_url}></video>
									<div class="btn-row">
										<a class="btn btn-sm" href={cap.video_url} download={cap.name}>Download MP4</a>
										{#if cap.srt_url}
											<a class="btn btn-ghost btn-sm" href={cap.srt_url} download>SRT</a>
										{/if}
										<button
											class="btn btn-primary btn-sm"
											disabled={transferringUrl !== null}
											onclick={() => sendToExports(cap.video_url!, cap.name, cap.name)}
										>
											Send to Exports
										</button>
									</div>
								</article>
							{:else if cap.srt_url}
								<div class="artifact-card">
									<span class="pill" data-status="done">Subtitles</span>
									<a class="btn btn-sm" href={cap.srt_url} download={cap.name}>Download {cap.name}</a>
								</div>
							{/if}
						{/each}

						{#each job.artifacts.packages as pkg (pkg.index)}
							<article class="artifact-card">
								<div class="artifact-head">
									<span class="pill" data-status="done">AI Package #{pkg.index + 1}</span>
								</div>
								{#if pkg.hook}<p><strong>Hook:</strong> {pkg.hook}</p>{/if}
								{#if pkg.title}<p class="muted small"><strong>Title:</strong> {pkg.title}</p>{/if}
								{#if pkg.thumbnail_url}
									<img class="thumb" src={pkg.thumbnail_url} alt="Generated thumbnail" />
								{/if}
								<div class="btn-row">
									{#if pkg.effects_url || pkg.hooked_url}
										{@const bestUrl = pkg.effects_url || pkg.hooked_url!}
										<a class="btn btn-sm" href={bestUrl} download>Download video</a>
										<button
											class="btn btn-primary btn-sm"
											disabled={transferringUrl !== null}
											onclick={() => sendToExports(bestUrl, pkg.title || `clip_${pkg.index}`, `clip_${pkg.index}.mp4`)}
										>
											Send to Exports
										</button>
									{/if}
									{#if pkg.thumbnail_url}
										<a class="btn btn-ghost btn-sm" href={pkg.thumbnail_url} download>Thumbnail</a>
									{/if}
								</div>
							</article>
						{/each}
					</div>
				</div>
			{/if}
		</section>
	</div>
</div>

<style>
	.head {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: flex-end;
		gap: 16px;
	}

	.head h1 {
		margin: 10px 0 8px;
		font-size: clamp(1.8rem, 3.2vw, 2.5rem);
	}

	.head p {
		max-width: 60ch;
		font-size: 13.5px;
	}

	.services {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
	}

	.grid {
		display: grid;
		grid-template-columns: minmax(300px, 370px) minmax(0, 1fr);
		gap: 18px;
		align-items: start;
	}

	@media (max-width: 960px) {
		.grid {
			grid-template-columns: minmax(0, 1fr);
		}
	}

	.sidebar,
	.workspace {
		display: flex;
		flex-direction: column;
		gap: 14px;
		min-width: 0;
	}

	.stack {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.stack .label {
		margin-bottom: 0;
	}

	.row-2 {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px;
	}

	.row-3 {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 10px;
	}

	.select,
	.text-input,
	.file-input {
		width: 100%;
		padding: 8px 10px;
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		background: rgba(0, 0, 0, 0.35);
		color: var(--text);
		font-size: 13px;
	}

	.check {
		display: flex;
		align-items: center;
		gap: 9px;
		font-size: 13.5px;
		cursor: pointer;
	}

	.check input {
		accent-color: var(--accent);
	}

	.summary-head {
		cursor: pointer;
		list-style: none;
	}

	.sep-line {
		width: 100%;
		border: 0;
		border-top: 1px solid var(--line);
		margin: 4px 0;
	}

	.plat-row,
	.btn-row {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.stage-strip {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.stage-pill {
		padding: 6px 12px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.03);
		color: var(--muted);
		font-size: 12.5px;
		cursor: pointer;
	}

	.stage-pill[data-done='true'] {
		border-color: rgba(98, 224, 160, 0.38);
		color: var(--ok);
	}

	.stage-pill[data-selected='true'] {
		border-color: var(--accent);
		background: var(--accent-soft);
		color: var(--text);
	}

	.stage-pill:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}

	.ok-notice {
		border-color: rgba(98, 224, 160, 0.35);
		background: rgba(98, 224, 160, 0.08);
		color: #b8f5d4;
		white-space: pre-line;
	}

	.clip-list,
	.artifact-grid {
		display: grid;
		gap: 12px;
	}

	.artifact-grid {
		grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
	}

	.clip-card,
	.artifact-card {
		display: flex;
		flex-direction: column;
		gap: 10px;
		padding: 14px;
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		background: rgba(0, 0, 0, 0.25);
	}

	.clip-top,
	.artifact-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}

	.clip-meta {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}

	.clip-title {
		font-weight: 600;
		font-size: 14px;
	}

	video,
	.thumb {
		width: 100%;
		max-height: 320px;
		border-radius: var(--radius-sm);
		background: #000;
		object-fit: contain;
	}

	.small {
		font-size: 12.5px;
	}

	.tiny {
		font-size: 11px;
	}
</style>
