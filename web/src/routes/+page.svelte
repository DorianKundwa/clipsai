<script lang="ts">
	import DropZone from '#lib/components/DropZone.svelte';
	import { videoStore } from '#lib/stores/videoStore.svelte';

	const steps = [
		{
			index: '01',
			title: 'Trim',
			body: 'Scrub the canvas timeline, drag the in and out handles, and see the exact cut before you render it.'
		},
		{
			index: '02',
			title: 'Reframe & grade',
			body: 'Crop to 9:16, 1:1 or 16:9 with a live framing guide, then pick a look — warm, cool, punch or mono.'
		},
		{
			index: '03',
			title: 'Render & download',
			body: 'FFmpeg.wasm encodes H.264 in a Web Worker, so playback and scrubbing stay smooth while clips render.'
		},
		{
			index: '04',
			title: 'Metadata & publish',
			body: 'DeepSeek drafts the title, caption and hashtags from the export, then IndiePost posts it to your linked accounts.'
		}
	];

	const current = $derived(videoStore.source);
</script>

<svelte:head>
	<title>ClipsAI Studio — edit video in the browser</title>
	<meta
		name="description"
		content="A local-first video trimmer and reframer built on ffmpeg.wasm, running in a Web Worker."
	/>
</svelte:head>

<div class="page">
	<section class="hero">
		<span class="eyebrow">ffmpeg.wasm · runs locally</span>

		<h1>Cut, reframe and grade clips<br /><span class="accent">without uploading them.</span></h1>

		<p class="lede">
			ClipsAI Studio is a browser-native production bench. Your footage stays on this machine:
			decoding, filtering and H.264 encoding all happen inside a dedicated worker thread.
		</p>

		<div class="actions">
			<a class="btn btn-primary" href="/pipeline">Auto AI pipeline</a>
			{#if current}
				<a class="btn" href="/studio">Continue with {current.name}</a>
			{:else}
				<a class="btn" href="/studio">Open manual studio</a>
			{/if}
			<a class="btn btn-ghost" href="/exports">
				View exports
				{#if videoStore.activeJobs > 0}
					<span class="pill" data-status="rendering">{videoStore.activeJobs} rendering</span>
				{/if}
			</a>
		</div>

		<DropZone
			title={current ? `Replace ${current.name}` : 'Start with a clip'}
			subtitle="Nothing leaves this device — no upload, no server round trip."
		/>
	</section>

	<section class="steps" aria-label="How it works">
		{#each steps as step (step.index)}
			<article class="step">
				<span class="index mono">{step.index}</span>
				<h2>{step.title}</h2>
				<p class="muted">{step.body}</p>
			</article>
		{/each}
	</section>

	<section class="panel tech">
		<div class="panel-head">
			<h2>Under the hood</h2>
			<span class="mono muted tiny">SharedArrayBuffer ready</span>
		</div>
		<div class="panel-body tech-body">
			<ul>
				<li>
					<strong>Cross-origin isolated.</strong> COOP <code>same-origin</code> + COEP
					<code>require-corp</code> are attached by SvelteKit's server hook and by Vite's dev
					server, which is what unlocks the multithreaded ffmpeg core.
				</li>
				<li>
					<strong>Off the main thread.</strong> The worker owns the wasm instance and streams
					progress back, so the 60fps preview and timeline scrubbing never wait on an encode.
				</li>
				<li>
					<strong>Queued, not parallel.</strong> One FFmpeg instance renders jobs back to back —
					bounded memory instead of N competing wasm heaps.
				</li>
				<li>
					<strong>Keys stay server-side.</strong> The DeepSeek and IndiePost keys are read by
					SvelteKit endpoints from the same <code>.env</code> as the Python pipeline. The
					browser only ever sends the clip and receives generated text or post links.
				</li>
			</ul>
		</div>
	</section>
</div>

<style>
	.hero {
		display: flex;
		flex-direction: column;
		gap: 20px;
		max-width: 820px;
		padding-block: 26px 6px;
	}

	.hero h1 {
		font-size: clamp(2.1rem, 5vw, 3.5rem);
	}

	.accent {
		color: var(--accent);
	}

	.lede {
		max-width: 60ch;
		color: var(--muted);
		font-size: 16px;
		line-height: 1.6;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px;
	}

	.steps {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
		gap: 14px;
	}

	.step {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 20px;
		border: 1px solid var(--line);
		border-radius: var(--radius);
		background: rgba(255, 255, 255, 0.018);
	}

	.index {
		color: var(--accent);
		font-size: 11px;
		letter-spacing: 0.14em;
	}

	.step h2 {
		font-size: 1.05rem;
	}

	.step p {
		font-size: 13.5px;
	}

	.tech-body ul {
		display: grid;
		gap: 12px;
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.tech-body li {
		padding-left: 16px;
		border-left: 2px solid var(--line-strong);
		color: var(--muted);
		font-size: 13.5px;
		line-height: 1.55;
	}

	.tech-body strong {
		color: var(--text);
	}

	code {
		padding: 1px 5px;
		border: 1px solid var(--line);
		border-radius: 5px;
		background: rgba(0, 0, 0, 0.35);
		font-family: var(--mono);
		font-size: 12px;
	}

	.tiny {
		font-size: 10.5px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}
</style>
