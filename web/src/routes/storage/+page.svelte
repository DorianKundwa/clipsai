<script lang="ts">
	import { onMount } from 'svelte';
	import { formatBytes } from '#lib/video';

	interface JobDir {
		job_id: string;
		size: number;
		files: number;
		created: string;
		updated: string;
		age_days: number;
		live: boolean;
		running: boolean;
	}

	interface Retention {
		older_than_days: number;
		keep_latest: number;
		max_total_gb: number;
	}

	interface Workspace {
		name: string;
		root: string;
		path: string;
		size: number;
		files: number;
		updated: string;
		age_days: number;
	}

	interface StorageState {
		root: string;
		jobs: JobDir[];
		jobs_bytes: number;
		jobs_count: number;
		workspaces: Workspace[];
		workspaces_bytes: number;
		workspace_roots: Record<string, string>;
		disk_total_bytes: number;
		disk_free_bytes: number;
		retention: Retention;
	}

	interface CleanupResult {
		removed: JobDir[];
		freed_bytes: number;
		kept: number;
		dry_run: boolean;
	}

	let storage = $state<StorageState | null>(null);
	let loading = $state(false);
	let busy = $state<string | null>(null);
	let error = $state<string | null>(null);
	let message = $state<string | null>(null);

	let olderThanDays = $state(30);
	let keepLatest = $state(20);
	let maxTotalGb = $state(0);

	async function load(): Promise<void> {
		loading = true;
		error = null;
		try {
			const response = await fetch('/api/storage');
			const data = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(data.error ?? `HTTP ${response.status}`);
			storage = data as StorageState;
			olderThanDays = data.retention?.older_than_days ?? 30;
			keepLatest = data.retention?.keep_latest ?? 20;
			maxTotalGb = data.retention?.max_total_gb ?? 0;
		} catch (problem) {
			error = problem instanceof Error ? problem.message : 'Could not read storage usage.';
		} finally {
			loading = false;
		}
	}

	async function cleanup(dryRun: boolean): Promise<void> {
		busy = dryRun ? 'preview' : 'cleanup';
		error = null;
		message = null;
		try {
			const response = await fetch('/api/storage/cleanup', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					older_than_days: Number(olderThanDays),
					keep_latest: Number(keepLatest),
					max_total_gb: Number(maxTotalGb),
					dry_run: dryRun
				})
			});
			const data = (await response.json().catch(() => ({}))) as CleanupResult & { error?: string };
			if (!response.ok) throw new Error(data.error ?? `HTTP ${response.status}`);

			const count = data.removed?.length ?? 0;
			message = count
				? `${dryRun ? 'Would delete' : 'Deleted'} ${count} job${count === 1 ? '' : 's'} (${formatBytes(data.freed_bytes)}). ${data.kept} kept.`
				: 'Nothing matched the policy — no job folders were removed.';

			if (!dryRun) await load();
		} catch (problem) {
			error = problem instanceof Error ? problem.message : 'Cleanup failed.';
		} finally {
			busy = null;
		}
	}

	async function removeJob(job: JobDir): Promise<void> {
		if (!window.confirm(`Delete job ${job.job_id} and its ${formatBytes(job.size)} of files?`)) {
			return;
		}
		busy = job.job_id;
		error = null;
		message = null;
		try {
			const response = await fetch(`/api/pipeline/jobs/${encodeURIComponent(job.job_id)}`, {
				method: 'DELETE'
			});
			const data = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(data.error ?? `HTTP ${response.status}`);
			message = `Deleted ${job.job_id}, freed ${formatBytes(data.freed_bytes ?? 0)}.`;
			await load();
		} catch (problem) {
			error = problem instanceof Error ? problem.message : 'Delete failed.';
		} finally {
			busy = null;
		}
	}

	async function removeWorkspace(workspace: Workspace): Promise<void> {
		const where = storage?.workspace_roots?.[workspace.root] ?? workspace.root;
		if (
			!window.confirm(
				`Delete workspace ${workspace.name} (${formatBytes(workspace.size)}) from ${where}?\n\nThis removes the folder and everything in it, including any finished clips inside.`
			)
		) {
			return;
		}
		busy = `workspace:${workspace.root}/${workspace.name}`;
		error = null;
		message = null;
		try {
			const response = await fetch(
				`/api/storage/workspaces/${encodeURIComponent(workspace.root)}/${encodeURIComponent(workspace.name)}`,
				{ method: 'DELETE' }
			);
			const data = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(data.error ?? `HTTP ${response.status}`);
			message = `Deleted workspace ${workspace.name}, freed ${formatBytes(data.freed_bytes ?? 0)}.`;
			await load();
		} catch (problem) {
			error = problem instanceof Error ? problem.message : 'Delete failed.';
		} finally {
			busy = null;
		}
	}

	async function compactJob(job: JobDir): Promise<void> {
		busy = job.job_id;
		error = null;
		message = null;
		try {
			const response = await fetch(
				`/api/pipeline/jobs/${encodeURIComponent(job.job_id)}/compact`,
				{ method: 'POST' }
			);
			const data = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(data.error ?? `HTTP ${response.status}`);
			const count = data.removed?.length ?? 0;
			message = count
				? `Compacted ${job.job_id}: removed ${count} intermediate file${count === 1 ? '' : 's'} (${formatBytes(data.freed_bytes ?? 0)}).`
				: `${job.job_id} has no intermediates left to remove.`;
			await load();
		} catch (problem) {
			error = problem instanceof Error ? problem.message : 'Compaction failed.';
		} finally {
			busy = null;
		}
	}

	function when(value: string): string {
		if (!value) return '';
		const date = new Date(value);
		return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
	}

	function usedPercent(): number {
		if (!storage || !storage.disk_total_bytes) return 0;
		const used = storage.disk_total_bytes - storage.disk_free_bytes;
		return Math.min(100, Math.round((used / storage.disk_total_bytes) * 100));
	}

	onMount(load);
</script>

<svelte:head>
	<title>Storage — ClipsAI</title>
</svelte:head>

<div class="page">
	<header class="head">
		<div>
			<span class="eyebrow">Output directory</span>
			<h1>Storage</h1>
			<p class="muted">
				Job folders written by the pipeline. Delete finished jobs, strip intermediates, or let a
				retention policy clean old runs automatically.
			</p>
		</div>
		<button class="btn btn-sm" onclick={load} disabled={loading}>
			{loading ? 'Refreshing…' : 'Refresh'}
		</button>
	</header>

	{#if error}
		<p class="notice">{error}</p>
	{/if}
	{#if message}
		<p class="notice" data-tone="ok">{message}</p>
	{/if}

	{#if storage}
		<section class="cards">
			<div class="panel">
				<div class="panel-body">
					<span class="label">Pipeline jobs</span>
					<strong class="value">{formatBytes(storage.jobs_bytes)}</strong>
					<span class="muted tiny">{storage.jobs_count} folder{storage.jobs_count === 1 ? '' : 's'}</span>
				</div>
			</div>
			<div class="panel">
				<div class="panel-body">
					<span class="label">Free on disk</span>
					<strong class="value">{formatBytes(storage.disk_free_bytes)}</strong>
					<span class="muted tiny">
						{usedPercent()}% of {formatBytes(storage.disk_total_bytes)} used
					</span>
				</div>
			</div>
			<div class="panel">
				<div class="panel-body">
					<span class="label">Campaign workspaces</span>
					<strong class="value">{formatBytes(storage.workspaces_bytes)}</strong>
					<span class="muted tiny">{storage.workspaces.length} folder{storage.workspaces.length === 1 ? '' : 's'}</span>
				</div>
			</div>
			<div class="panel wide">
				<div class="panel-body">
					<span class="label">Locations</span>
					<code class="mono tiny">{storage.root}</code>
					{#each Object.entries(storage.workspace_roots ?? {}) as [key, path] (key)}
						<code class="mono tiny block">{key}: {path}</code>
					{/each}
				</div>
			</div>
		</section>

		<section class="panel">
			<div class="panel-head">
				<h2>Retention policy</h2>
				<span class="mono tiny muted">runs at startup, or on demand</span>
			</div>
			<div class="panel-body">
				<div class="form">
					<label class="field">
						<span class="label">Delete jobs older than (days)</span>
						<input type="number" min="0" step="1" bind:value={olderThanDays} />
						<span class="unit">0 = ignore age</span>
					</label>
					<label class="field">
						<span class="label">Always keep newest</span>
						<input type="number" min="0" step="1" bind:value={keepLatest} />
						<span class="unit">jobs</span>
					</label>
					<label class="field">
						<span class="label">Total budget</span>
						<input type="number" min="0" step="1" bind:value={maxTotalGb} />
						<span class="unit">GB · 0 = no limit</span>
					</label>
				</div>
				<div class="actions">
					<button class="btn btn-ghost btn-sm" onclick={() => cleanup(true)} disabled={busy !== null}>
						{busy === 'preview' ? 'Checking…' : 'Preview'}
					</button>
					<button class="btn btn-sm" onclick={() => cleanup(false)} disabled={busy !== null}>
						{busy === 'cleanup' ? 'Cleaning…' : 'Clean now'}
					</button>
				</div>
			</div>
		</section>

		<section>
			<div class="section-head">
				<h2>Campaign workspaces</h2>
				<span class="mono tiny muted">{storage.workspaces?.length ?? 0}</span>
			</div>

			{#if !storage.workspaces || storage.workspaces.length === 0}
				<p class="muted small">No campaign folders in the workspace roots.</p>
			{:else}
				<div class="rows">
					{#each storage.workspaces as workspace (`${workspace.root}/${workspace.name}`)}
						<article class="row">
							<div class="row-main">
								<div class="row-title">
									<strong class="mono">{workspace.name}</strong>
									<span class="chip mono">{workspace.root}</span>
								</div>
								<p class="mono tiny muted">
									{formatBytes(workspace.size)}
									<span class="sep">·</span> {workspace.files} file{workspace.files === 1 ? '' : 's'}
									<span class="sep">·</span> {workspace.age_days}d old
									<span class="sep">·</span> {when(workspace.updated)}
								</p>
							</div>
							<div class="row-actions">
								<button
									class="btn btn-ghost btn-sm"
									onclick={() => removeWorkspace(workspace)}
									disabled={busy !== null}
								>
									{busy === `workspace:${workspace.root}/${workspace.name}` ? 'Deleting…' : 'Delete'}
								</button>
							</div>
						</article>
					{/each}
				</div>
			{/if}
		</section>

		<section>
			<div class="section-head">
				<h2>Job folders</h2>
				<span class="mono tiny muted">{storage.jobs_count}</span>
			</div>

			{#if storage.jobs.length === 0}
				<p class="muted small">No job folders in the output directory.</p>
			{:else}
				<div class="rows">
					{#each storage.jobs as job (job.job_id)}
						<article class="row">
							<div class="row-main">
								<div class="row-title">
									<strong class="mono">{job.job_id}</strong>
									<span class="pill" data-status={job.running ? 'rendering' : job.live ? 'done' : ''}>
										{job.running ? 'running' : job.live ? 'this session' : 'on disk'}
									</span>
								</div>
								<p class="mono tiny muted">
									{formatBytes(job.size)}
									<span class="sep">·</span> {job.files} file{job.files === 1 ? '' : 's'}
									<span class="sep">·</span> {job.age_days}d old
									{#if job.updated}
										<span class="sep">·</span> {when(job.updated)}
									{/if}
								</p>
							</div>
							<div class="row-actions">
								<button
									class="btn btn-ghost btn-sm"
									onclick={() => compactJob(job)}
									disabled={busy !== null || job.running}
									title="Remove trimmed cuts and reframes that a final render replaced"
								>
									{busy === job.job_id ? 'Working…' : 'Free space'}
								</button>
								<button
									class="btn btn-ghost btn-sm"
									onclick={() => removeJob(job)}
									disabled={busy !== null || job.running}
								>
									Delete
								</button>
							</div>
						</article>
					{/each}
				</div>
			{/if}
		</section>
	{/if}
</div>

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
		max-width: 60ch;
		font-size: 13.5px;
	}

	.page {
		display: flex;
		flex-direction: column;
		gap: 26px;
		padding-bottom: 40px;
	}

	.cards {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
		gap: 12px;
	}

	.cards .wide {
		grid-column: span 2;
	}

	.value {
		display: block;
		margin: 8px 0 4px;
		font-size: 22px;
		letter-spacing: -0.02em;
	}

	.form {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
		gap: 14px;
	}

	.actions {
		display: flex;
		gap: 8px;
		justify-content: flex-end;
		margin-top: 16px;
	}

	.section-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 12px;
		padding-bottom: 10px;
		border-bottom: 1px solid var(--line);
		margin-bottom: 12px;
	}

	.section-head h2 {
		margin: 0;
		font-size: 15px;
	}

	.rows {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 18px;
		padding: 14px 16px;
		border: 1px solid var(--line);
		border-radius: var(--radius);
		background: linear-gradient(180deg, var(--panel-2), var(--panel));
	}

	.row-main {
		display: flex;
		flex-direction: column;
		gap: 7px;
		min-width: 0;
		flex: 1 1 auto;
	}

	.row-title {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 10px;
	}

	.row-title strong {
		font-size: 13px;
	}

	.row-actions {
		display: flex;
		flex-shrink: 0;
		gap: 8px;
	}

	.sep {
		padding-inline: 2px;
		opacity: 0.5;
	}

	.tiny {
		font-size: 11px;
	}

	.small {
		font-size: 12.5px;
	}

	code {
		word-break: break-all;
	}

	code.block {
		display: block;
		margin-top: 4px;
	}

	@media (max-width: 700px) {
		.cards .wide {
			grid-column: auto;
		}

		.row {
			flex-direction: column;
			align-items: stretch;
		}

		.row-actions {
			justify-content: flex-end;
		}
	}
</style>
