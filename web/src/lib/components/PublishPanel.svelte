<script lang="ts">
	import { onMount } from 'svelte';
	import AccountTargets from '#lib/components/AccountTargets.svelte';
	import { videoStore, type RenderJob } from '#lib/stores/videoStore.svelte';
	import { indiePost } from '#lib/stores/indiepost.svelte';
	import { targets } from '#lib/stores/targets.svelte';
	import { MAX_BYTES, PLATFORMS, aspectForPlatforms, formatBytes } from '#lib/video';

	interface Props {
		job: RenderJob;
		onclose: () => void;
	}

	let { job, onclose }: Props = $props();

	const PRIVACY = [
		{ id: 'PUBLIC_TO_EVERYONE', label: 'Public' },
		{ id: 'MUTUAL_FOLLOW_FRIENDS', label: 'Friends' },
		{ id: 'FOLLOWER_OF_CREATOR', label: 'Followers' },
		{ id: 'SELF_ONLY', label: 'Only me' }
	];

	let aiConfigured = $state<boolean | null>(null);
	let generating = $state(false);
	let aiError = $state<string | null>(null);
	let brief = $state('');
	let hashtags = $state<string[]>([]);

	let selected = $derived(targets.selected);
	let caption = $state('');
	let youtubeTitle = $state('');
	let youtubeFormat = $state<'short' | 'long'>('short');
	let tiktokPrivacy = $state('PUBLIC_TO_EVERYONE');
	let aiGenerated = $state(false);

	let publishing = $state(false);
	let error = $state<string | null>(null);
	let result = $state<{ links: string[]; platforms: string[] } | null>(null);

	const loadingAccounts = $derived(indiePost.loading && !indiePost.loaded);
	const needsTitle = $derived(selected.includes('youtube'));
	const needsPrivacy = $derived(selected.includes('tiktok'));
	const recommendedAspect = $derived(aspectForPlatforms(selected, youtubeFormat));
	const frameMismatch = $derived(
		recommendedAspect !== null && recommendedAspect !== job.options.aspect
	);
	const canPublish = $derived(
		!publishing && selected.length > 0 && (!needsTitle || youtubeTitle.trim().length > 0)
	);

	// The page behind the dialog must not scroll while it is open.
	$effect(() => {
		const previous = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		return () => {
			document.body.style.overflow = previous;
		};
	});

	onMount(async () => {
		// Seeded once: the panel is keyed by job id, so `job` cannot change underneath it.
		youtubeTitle = job.label.slice(0, 100);

		await indiePost.load();

		try {
			const response = await fetch('/api/ai/metadata');
			const data = await response.json();
			aiConfigured = data.configured === true;
		} catch {
			aiConfigured = false;
		}
	});

	async function writeMetadata(): Promise<void> {
		generating = true;
		aiError = null;

		try {
			const response = await fetch('/api/ai/metadata', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					name: job.fileName,
					start: job.options.start,
					end: job.options.end,
					aspect: job.options.aspect,
					look: job.options.look,
					platforms: selected.length > 0 ? selected : [...PLATFORMS],
					brief,
					existingCaption: caption
				})
			});
			const data = await response.json().catch(() => ({}));

			if (!response.ok) {
				throw new Error(data.error ?? `Metadata generation failed (HTTP ${response.status}).`);
			}

			hashtags = Array.isArray(data.hashtags) ? data.hashtags : [];
			youtubeTitle = String(data.title ?? '').slice(0, 100) || youtubeTitle;
			caption = [String(data.caption ?? '').trim(), hashtags.map((tag) => `#${tag}`).join(' ')]
				.filter(Boolean)
				.join('\n\n');
			// The copy came from a model, so tick the platform disclosure for the user.
			aiGenerated = true;
		} catch (problem) {
			aiError = problem instanceof Error ? problem.message : 'Metadata generation failed.';
		} finally {
			generating = false;
		}
	}

	function stripTags(): void {
		caption = caption
			.replace(/#[a-z0-9_]+/gi, '')
			.replace(/[ \t]+\n/g, '\n')
			.trim();
		hashtags = [];
	}

	/** base64url JSON: header-safe, and keeps the request body a pure clip stream. */
	function encodeMetadata(value: unknown): string {
		const bytes = new TextEncoder().encode(JSON.stringify(value));
		let binary = '';
		for (const byte of bytes) binary += String.fromCharCode(byte);
		return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
	}

	async function publish(): Promise<void> {
		if (!canPublish || !job.url) return;

		publishing = true;
		error = null;
		result = null;

		try {
			// The rendered clip is already a Blob behind `job.url`, so read it as a
			// stream: nothing is copied into memory and nothing is buffered.
			const clip = await fetch(job.url);
			const size = job.size ?? Number(clip.headers.get('content-length')) ?? 0;
			if (!clip.body || !size) throw new Error('The rendered clip could not be read.');
			if (size > MAX_BYTES) {
				throw new Error(`This clip is ${formatBytes(size)}; IndiePost accepts up to 2 GB.`);
			}

			const response = await fetch('/api/indiepost/publish', {
				method: 'POST',
				headers: {
					'content-type': 'video/mp4',
					'x-clip-size': String(size),
					'x-clip-name': encodeURIComponent(job.fileName),
					'x-clipsai-publish': encodeMetadata({
						platforms: selected,
						caption,
						youtubeTitle,
						youtubeFormat,
						tiktokPrivacy,
						aiGenerated,
						when: 'now',
						// Stable per clip + destination set: a retry returns the existing
						// post instead of publishing a duplicate.
						idempotencyKey: `clipsai-${job.id}-${[...selected].sort().join('-')}`
					})
				},
				body: clip.body,
				// Half-duplex: the clip streams while the request is still open.
				duplex: 'half'
			} as RequestInit & { duplex: 'half' });
			const data = await response.json().catch(() => ({}));

			if (!response.ok) {
				throw new Error(data.error ?? `Publishing failed (HTTP ${response.status}).`);
			}

			const receipt = { links: data.links ?? [], platforms: data.platforms ?? selected };
			result = receipt;
			videoStore.markPublished(job.id, { ...receipt, at: Date.now() });
		} catch (problem) {
			error = problem instanceof Error ? problem.message : 'Publishing failed.';
		} finally {
			publishing = false;
		}
	}
</script>

<svelte:window
	onkeydown={(event) => {
		if (event.key === 'Escape' && !publishing) onclose();
	}}
/>

<div
	class="backdrop"
	role="presentation"
	onclick={(event) => {
		if (event.target === event.currentTarget) onclose();
	}}
>
	<div class="dialog" role="dialog" aria-modal="true" aria-labelledby="publish-title">
		<header>
			<div>
				<span class="label">Publish via IndiePost</span>
				<h2 id="publish-title">{job.fileName}</h2>
				<p class="mono muted small">
					{formatBytes(job.size ?? 0)} · {job.options.aspect} · {job.options.look}
					{#if indiePost.workspace}· {indiePost.workspace.name}{/if}
				</p>
			</div>
			<button class="btn btn-ghost btn-sm" onclick={onclose} aria-label="Close">Close</button>
		</header>

		<div class="body">
			{#if loadingAccounts}
				<p class="muted small">Checking linked accounts…</p>
			{:else if indiePost.configured === false}
				<p class="notice" data-tone="warn">
					IndiePost is not configured. Add <code>INDIEPOST_API_KEY</code> to the repository
					<code>.env</code> and restart the studio server.
				</p>
			{:else}
				{#if indiePost.message || indiePost.error}
					<p class="notice" data-tone="warn">{indiePost.message ?? indiePost.error}</p>
				{/if}

				<div>
					<div class="accounts-head">
						<span class="label">Linked accounts</span>
						<span class="mono tiny muted">
							{selected.length}/{indiePost.connected.length} selected
						</span>
					</div>
					<AccountTargets />
					{#if recommendedAspect}
						<p class="frame-note" data-warn={frameMismatch}>
							Recommended frame: <strong class="mono">{recommendedAspect}</strong>.
							{#if frameMismatch}
								This clip is {job.options.aspect} —
								<a href="/studio" onclick={() => onclose()}>re-render</a> for the best fit.
							{:else}
								This clip already matches.
							{/if}
						</p>
					{/if}
				</div>

				<div class="ai">
					<div class="ai-head">
						<span class="label">Metadata</span>
						<button
							class="btn btn-sm"
							onclick={writeMetadata}
							disabled={generating || aiConfigured === false}
						>
							{generating ? 'Writing…' : 'Write with DeepSeek'}
						</button>
					</div>

					<div class="field">
						<input
							type="text"
							bind:value={brief}
							maxlength="240"
							placeholder="Optional: what happens in this clip?"
						/>
					</div>

					{#if aiConfigured === false}
						<p class="muted tiny">
							DeepSeek key not set — add <code>DEEPSEEK_API_KEY</code> to <code>.env</code>.
						</p>
					{/if}

					{#if aiError}
						<p class="notice">{aiError}</p>
					{/if}

					{#if hashtags.length > 0}
						<div class="tags">
							{#each hashtags as tag (tag)}
								<span class="tag mono">#{tag}</span>
							{/each}
							<button class="btn btn-ghost btn-sm" onclick={stripTags}>Remove tags</button>
						</div>
					{/if}
				</div>

				<div>
					<span class="label">Caption</span>
					<textarea
						class="textarea"
						rows="4"
						maxlength="2200"
						bind:value={caption}
						placeholder="Write the caption, or generate one with DeepSeek above…"
					></textarea>
					<p class="counter mono muted">{caption.length}/2200</p>
				</div>

				{#if needsTitle}
					<div class="row">
						<label class="grow">
							<span class="label">YouTube title</span>
							<div class="field">
								<input
									type="text"
									maxlength="100"
									bind:value={youtubeTitle}
									placeholder="Short, searchable title"
								/>
							</div>
							<p class="counter mono muted">{youtubeTitle.length}/100</p>
						</label>
						<label>
							<span class="label">Format</span>
							<div class="field">
								<select bind:value={youtubeFormat}>
									<option value="short">Short</option>
									<option value="long">Long</option>
								</select>
							</div>
						</label>
					</div>
				{/if}

				{#if needsPrivacy}
					<div class="row">
						<label class="grow">
							<span class="label">TikTok privacy</span>
							<div class="field">
								<select bind:value={tiktokPrivacy}>
									{#each PRIVACY as level (level.id)}
										<option value={level.id}>{level.label}</option>
									{/each}
								</select>
							</div>
						</label>
						<label class="check">
							<input type="checkbox" bind:checked={aiGenerated} />
							<span>AI-generated</span>
						</label>
					</div>
				{/if}

				{#if error}
					<p class="notice">{error}</p>
				{/if}

				{#if result}
					<p class="success">
						Published to {result.platforms.join(', ')}.
						{#if result.links.length > 0 && /^https?:/i.test(result.links[0])}
							<a href={result.links[0]} target="_blank" rel="noreferrer">Open post ↗</a>
						{/if}
					</p>
				{/if}

				<div class="footer">
					<span class="muted small">
						Uploads the rendered MP4 and posts now. Both API keys stay on the server.
					</span>
					<button class="btn btn-primary" onclick={publish} disabled={!canPublish}>
						{publishing ? 'Publishing…' : `Publish to ${selected.length || 0}`}
					</button>
				</div>
			{/if}
		</div>
	</div>
</div>

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 50;
		display: grid;
		place-items: center;
		padding: 24px;
		background: rgba(4, 5, 7, 0.72);
		backdrop-filter: blur(6px);
	}

	.dialog {
		display: flex;
		flex-direction: column;
		width: min(620px, 100%);
		max-height: min(88vh, 860px);
		overflow: hidden;
		border: 1px solid var(--line-strong);
		border-radius: var(--radius);
		background: linear-gradient(180deg, var(--panel-2), var(--panel));
		box-shadow: 0 30px 80px rgba(0, 0, 0, 0.55);
	}

	header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
		padding: 18px 20px;
		border-bottom: 1px solid var(--line);
	}

	header h2 {
		margin: 4px 0 4px;
		font-size: 1.05rem;
		word-break: break-all;
	}

	.small {
		font-size: 12px;
	}

	.tiny {
		font-size: 11px;
	}

	.body {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 18px 20px 20px;
		overflow-y: auto;
	}

	.accounts-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
	}

	.accounts-head .label {
		margin-bottom: 8px;
	}

	.frame-note {
		margin-top: 8px;
		color: var(--muted);
		font-size: 11.5px;
	}

	.frame-note[data-warn='true'] {
		color: #ffe0ad;
	}

	.frame-note a {
		color: var(--accent);
		text-decoration: underline;
	}

	.ai {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px;
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		background: rgba(255, 255, 255, 0.02);
	}

	.ai-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	.ai-head .label {
		margin-bottom: 0;
	}

	.tags {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
	}

	.tag {
		padding: 2px 8px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: rgba(215, 255, 62, 0.08);
		color: var(--accent);
		font-size: 10.5px;
	}

	.textarea {
		width: 100%;
		min-height: 92px;
		padding: 10px 12px;
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		background: rgba(0, 0, 0, 0.28);
		font: inherit;
		font-size: 13.5px;
		line-height: 1.5;
		resize: vertical;
	}

	.textarea:focus {
		outline: 2px solid var(--accent);
		outline-offset: 1px;
	}

	.counter {
		margin-top: 4px;
		font-size: 10.5px;
		text-align: right;
	}

	.row {
		display: flex;
		align-items: flex-end;
		gap: 10px;
	}

	.grow {
		flex: 1 1 auto;
		min-width: 0;
	}

	.field input {
		font-size: 13px;
	}

	.field select {
		width: 100%;
		border: 0;
		background: transparent;
		font-size: 13px;
		outline: none;
	}

	.check {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		padding-bottom: 8px;
		color: var(--muted);
		font-size: 12px;
	}

	.check input {
		accent-color: var(--accent);
	}

	.success {
		padding: 10px 12px;
		border: 1px solid rgba(98, 224, 160, 0.35);
		border-radius: var(--radius-sm);
		background: rgba(98, 224, 160, 0.08);
		color: #b8f3d6;
		font-size: 13px;
	}

	.success a {
		color: var(--accent);
		text-decoration: underline;
	}

	.footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 14px;
		padding-top: 4px;
		border-top: 1px solid var(--line);
		margin-top: 4px;
	}

	.footer .muted {
		max-width: 34ch;
		line-height: 1.4;
	}

	code {
		padding: 1px 4px;
		border: 1px solid var(--line);
		border-radius: 4px;
		background: rgba(0, 0, 0, 0.35);
		font-family: var(--mono);
		font-size: 11.5px;
	}

	@media (max-width: 520px) {
		.backdrop {
			padding: 0;
		}

		.dialog {
			max-height: 100vh;
			border-radius: 0;
		}

		.footer {
			flex-direction: column;
			align-items: stretch;
		}
	}
</style>
