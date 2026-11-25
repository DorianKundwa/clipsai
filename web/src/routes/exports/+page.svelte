<script lang="ts">
	import { onMount } from 'svelte';
	import AccountTargets from '#lib/components/AccountTargets.svelte';
	import PublishPanel from '#lib/components/PublishPanel.svelte';
	import { indiePost } from '#lib/stores/indiepost.svelte';
	import { targets } from '#lib/stores/targets.svelte';
	import { videoStore } from '#lib/stores/videoStore.svelte';
	import { formatBytes, formatTime } from '#lib/video';

	const jobs = $derived(videoStore.jobs);
	const active = $derived(videoStore.activeJobs);

	// Track by id: the job objects in the store are replaced as progress updates.
	let publishingId = $state<string | null>(null);
	const publishingJob = $derived(
		publishingId ? (jobs.find((job) => job.id === publishingId) ?? null) : null
	);

	onMount(() => {
		void indiePost.load();
	});

	function renderTime(job: (typeof videoStore.jobs)[number]): string {
		if (!job.startedAt) return 'queued';
		const end = job.finishedAt ?? Date.now();
		const seconds = Math.max(0, (end - job.startedAt) / 1000);
		return `${seconds.toFixed(1)}s`;
	}
</script>

<svelte:head>
	<title>Exports — ClipsAI</title>
</svelte:head>

<div class="page">
	<header class="head">
		<div>
			<span class="eyebrow">Render queue</span>
			<h1>Exports</h1>
			<p class="muted">
				Rendered clips live in browser memory as blobs. Download what you need — reloading the tab
				clears the queue.
			</p>
		</div>

		<div class="stats">
			<div class="stat">
				<span class="label">Finished</span>
				<strong class="mono">{videoStore.finishedJobs.length}</strong>
			</div>
			<div class="stat">
				<span class="label">In flight</span>
				<strong class="mono">{active}</strong>
			</div>
			<div class="stat">
				<span class="label">Total size</span>
				<strong class="mono">{formatBytes(videoStore.exportedBytes)}</strong>
			</div>
		</div>
	</header>

	<div class="linked">
		<span class="label">
			Linked accounts{#if indiePost.workspace}
				<span class="mono">· {indiePost.workspace.name}</span>
			{/if}
		</span>
		<AccountTargets variant="chips" />
		{#if indiePost.message || indiePost.error}
			<span class="muted tiny">{indiePost.message ?? indiePost.error}</span>
		{:else if indiePost.loaded}
			<span class="mono tiny muted">→ {targets.selected.length} selected</span>
		{/if}
	</div>

	{#if jobs.length === 0}
		<section class="empty panel">
			<div class="panel-body">
				<h2>Nothing rendered yet</h2>
				<p class="muted">
					Trim a clip in the studio and press <strong>Render clip</strong>. Encoding happens in a
					worker, so you can keep editing while it runs.
				</p>
				<div class="actions">
					<a class="btn btn-primary" href="/studio">Open the studio</a>
				</div>
			</div>
		</section>
	{:else}
		<div class="toolbar">
			<span class="mono muted">{jobs.length} job{jobs.length === 1 ? '' : 's'}</span>
			<button
				class="btn btn-ghost btn-sm"
				onclick={() => videoStore.clearFinished()}
				disabled={videoStore.finishedJobs.length === 0}
			>
				Clear finished
			</button>
		</div>

		<div class="list">
			{#each jobs as job (job.id)}
				<article class="job">
					<div class="job-main">
						<div class="job-title">
							<strong>{job.label}</strong>
							<span class="pill" data-status={job.status}>{job.status}</span>
						</div>

						<p class="meta mono muted">
							{formatTime(job.options.start)} → {formatTime(job.options.end)}
							<span class="sep">·</span> {job.options.aspect}
							<span class="sep">·</span> {job.options.look}
							{#if job.size}<span class="sep">·</span> {formatBytes(job.size)}{/if}
							<span class="sep">·</span> {renderTime(job)}
						</p>

						{#if job.published}
							<p class="published">
								<span class="pill" data-status="published">published</span>
								<span class="mono muted">{job.published.platforms.join(' · ')}</span>
								{#if job.published.links[0] && /^https?:/i.test(job.published.links[0])}
									<a class="mono" href={job.published.links[0]} target="_blank" rel="noreferrer">
										open ↗
									</a>
								{/if}
							</p>
						{/if}

						{#if job.status === 'rendering' || job.status === 'queued'}
							<div class="progress">
								<span style="width: {(job.status === 'queued' ? 0 : job.progress * 100).toFixed(1)}%"></span>
							</div>
							<p class="status-note mono">
								{job.status === 'queued' ? 'waiting for the encoder' : `encoding ${Math.round(job.progress * 100)}%`}
							</p>
						{/if}

						{#if job.error}
							<p class="notice">{job.error}</p>
						{/if}
					</div>

					<div class="job-actions">
						{#if job.url}
							<button class="btn btn-sm" onclick={() => (publishingId = job.id)}>
								{job.published ? 'Publish again' : 'Publish'}
							</button>
							<a class="btn btn-primary btn-sm" href={job.url} download={job.fileName}>Download</a>
						{/if}
						{#if job.status !== 'rendering'}
							<button class="btn btn-ghost btn-sm" onclick={() => videoStore.removeJob(job.id)}>
								Remove
							</button>
						{/if}
					</div>
				</article>
			{/each}
		</div>
	{/if}
</div>

{#if publishingJob}
	<PublishPanel job={publishingJob} onclose={() => (publishingId = null)} />
{/if}

<style>
	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		justify-content: space-between;
		gap: 20px;
		padding-top: 12px;
	}

	.head h1 {
		margin: 12px 0 8px;
		font-size: clamp(1.9rem, 3.4vw, 2.6rem);
	}

	.head p {
		max-width: 54ch;
		font-size: 13.5px;
	}

	.stats {
		display: flex;
		gap: 10px;
	}

	.stat {
		min-width: 92px;
		padding: 10px 14px;
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		background: rgba(255, 255, 255, 0.02);
	}

	.stat .label {
		margin-bottom: 2px;
		font-size: 10px;
	}

	.stat strong {
		font-size: 16px;
	}

	.linked {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
		padding-bottom: 2px;
	}

	.linked .label {
		margin: 0 4px 0 0;
	}

	.tiny {
		font-size: 11px;
	}

	.toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		font-size: 12px;
	}

	.list {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.job {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 18px;
		padding: 16px 18px;
		border: 1px solid var(--line);
		border-radius: var(--radius);
		background: linear-gradient(180deg, var(--panel-2), var(--panel));
	}

	.job-main {
		display: flex;
		flex-direction: column;
		gap: 7px;
		min-width: 0;
		flex: 1 1 auto;
	}

	.job-title {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 0;
	}

	.job-title strong {
		overflow: hidden;
		font-size: 14px;
		font-weight: 600;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.meta {
		font-size: 11.5px;
	}

	.sep {
		padding-inline: 2px;
		opacity: 0.5;
	}

	.published {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
		font-size: 11.5px;
	}

	.published a {
		color: var(--accent);
		text-decoration: underline;
	}

	.status-note {
		color: var(--accent);
		font-size: 10.5px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}

	.job-actions {
		display: flex;
		align-items: center;
		gap: 6px;
		flex: 0 0 auto;
	}

	.empty .panel-body {
		gap: 12px;
		align-items: flex-start;
	}

	.actions {
		display: flex;
		gap: 8px;
		margin-top: 4px;
	}

	@media (max-width: 700px) {
		.job {
			flex-direction: column;
			align-items: stretch;
		}

		.job-actions {
			justify-content: flex-end;
		}

		.stats {
			width: 100%;
		}

		.stat {
			flex: 1;
			min-width: 0;
		}
	}
</style>
