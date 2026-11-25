<script lang="ts">
	import { onMount } from 'svelte';
	import { formatBytes } from '#lib/video';

	interface MediaItem {
		mediaId: string;
		filename: string;
		mime: string;
		size: number;
		inUse: boolean;
	}

	interface PostItem {
		platform: string;
		status: string;
		format: string | null;
		externalPostId: string | null;
		postedAt: string | null;
	}

	interface PostGroup {
		postGroupId: string;
		status: string;
		scheduledAt: string | null;
		platforms: string[];
		posts: PostItem[];
	}

	let media = $state<MediaItem[]>([]);
	let posts = $state<PostGroup[]>([]);
	let loading = $state(false);
	let busy = $state<string | null>(null);
	let error = $state<string | null>(null);
	let configured = $state<boolean | null>(null);

	/** Map IndiePost's statuses onto the pill tones the stylesheet defines. */
	function tone(status: string): 'published' | 'rendering' | 'error' {
		const value = status.toLowerCase();
		if (['posted', 'published', 'done'].includes(value)) return 'published';
		if (['failed', 'error', 'rejected'].includes(value)) return 'error';
		return 'rendering';
	}

	function when(value: string | null): string {
		if (!value) return '';
		const date = new Date(value);
		return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
	}

	async function load(): Promise<void> {
		loading = true;
		error = null;

		try {
			const [mediaResponse, postsResponse] = await Promise.all([
				fetch('/api/indiepost/media'),
				fetch('/api/indiepost/posts')
			]);
			const mediaData = await mediaResponse.json().catch(() => ({}));
			const postsData = await postsResponse.json().catch(() => ({}));

			configured = mediaData.configured !== false;
			media = Array.isArray(mediaData.items) ? mediaData.items : [];
			posts = Array.isArray(postsData.posts) ? postsData.posts : [];

			const problems = [mediaData.message, postsData.message].filter(
				(value): value is string => typeof value === 'string' && value.length > 0
			);
			error = problems.length > 0 ? problems.join(' ') : null;
		} catch {
			error = 'Could not reach the studio server.';
		} finally {
			loading = false;
		}
	}

	async function remove(kind: 'media' | 'posts', id: string, question: string): Promise<void> {
		if (!window.confirm(question)) return;

		busy = id;
		error = null;

		try {
			const response = await fetch(`/api/indiepost/${kind}/${encodeURIComponent(id)}`, {
				method: 'DELETE'
			});
			const data = await response.json().catch(() => ({}));

			if (!response.ok) {
				throw new Error(data.error ?? `Delete failed (HTTP ${response.status}).`);
			}

			if (kind === 'media') media = media.filter((item) => item.mediaId !== id);
			else posts = posts.filter((group) => group.postGroupId !== id);
		} catch (problem) {
			error = problem instanceof Error ? problem.message : 'Delete failed.';
		} finally {
			busy = null;
		}
	}

	onMount(load);
</script>

<svelte:head>
	<title>Library — ClipsAI</title>
</svelte:head>

<div class="page">
	<header class="head">
		<div>
			<span class="eyebrow">IndiePost</span>
			<h1>Library</h1>
			<p class="muted">
				Post groups scheduled or published around today, and the media IndiePost still holds for
				your workspace.
			</p>
		</div>
		<button class="btn btn-sm" onclick={load} disabled={loading}>
			{loading ? 'Refreshing…' : 'Refresh'}
		</button>
	</header>

	{#if configured === false}
		<p class="notice" data-tone="warn">
			IndiePost is not configured. Add <code>INDIEPOST_API_KEY</code> to the repository
			<code>.env</code> and restart the studio server.
		</p>
	{:else}
		{#if error}
			<p class="notice">{error}</p>
		{/if}

		<section>
			<div class="section-head">
				<h2>Posts</h2>
				<span class="mono tiny muted">{posts.length} group{posts.length === 1 ? '' : 's'}</span>
			</div>

			{#if posts.length === 0}
				<p class="muted small">{loading ? 'Loading…' : 'Nothing posted or scheduled in this window.'}</p>
			{:else}
				<div class="rows">
					{#each posts as group (group.postGroupId)}
						<article class="row">
							<div class="row-main">
								<div class="row-title">
									<span class="pill" data-status={tone(group.status)}>{group.status}</span>
									<span class="mono tiny muted">
										{group.scheduledAt ? `scheduled ${when(group.scheduledAt)}` : group.postGroupId}
									</span>
								</div>
								<div class="chips">
									{#each group.posts as post (`${group.postGroupId}-${post.platform}`)}
										<span class="chip mono" data-status={tone(post.status)}>
											{post.platform} · {post.status}
											{#if post.externalPostId}
												<span class="sep">·</span> {post.externalPostId}
											{/if}
										</span>
									{/each}
								</div>
							</div>
							<button
								class="btn btn-ghost btn-sm"
								onclick={() => remove('posts', group.postGroupId, 'Delete this post from every platform?')}
								disabled={busy !== null}
							>
								{busy === group.postGroupId ? 'Deleting…' : 'Delete'}
							</button>
						</article>
					{/each}
				</div>
			{/if}
		</section>

		<section>
			<div class="section-head">
				<h2>Media</h2>
				<span class="mono tiny muted">{media.length} file{media.length === 1 ? '' : 's'}</span>
			</div>

			{#if media.length === 0}
				<p class="muted small">{loading ? 'Loading…' : 'No media stored yet.'}</p>
			{:else}
				<div class="rows">
					{#each media as item (item.mediaId)}
						<article class="row">
							<div class="row-main">
								<div class="row-title">
									<strong class="mono">{item.filename || item.mediaId}</strong>
									{#if item.inUse}
										<span class="pill" data-status="rendering">in use</span>
									{/if}
								</div>
								<p class="mono tiny muted">
									{formatBytes(item.size)}
									<span class="sep">·</span> {item.mime || 'unknown type'}
								</p>
							</div>
							<button
								class="btn btn-ghost btn-sm"
								onclick={() => remove('media', item.mediaId, `Delete ${item.filename || 'this file'} from IndiePost?`)}
								disabled={busy !== null || item.inUse}
								title={item.inUse ? 'Used by a post; delete the post first.' : undefined}
							>
								{busy === item.mediaId ? 'Deleting…' : 'Delete'}
							</button>
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
		max-width: 56ch;
		font-size: 13.5px;
	}

	.page {
		display: flex;
		flex-direction: column;
		gap: 26px;
		padding-bottom: 40px;
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
		letter-spacing: 0.01em;
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
		min-width: 0;
	}

	.row-title strong {
		overflow: hidden;
		font-size: 13px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.chip {
		padding: 3px 9px;
		border: 1px solid var(--line);
		border-radius: 999px;
		color: var(--muted);
		font-size: 10.5px;
	}

	.chip[data-status='published'] {
		border-color: rgba(98, 224, 160, 0.35);
		color: var(--ok);
	}

	.chip[data-status='error'] {
		border-color: rgba(255, 123, 114, 0.4);
		color: var(--danger);
	}

	.sep {
		padding-inline: 2px;
		opacity: 0.5;
	}

	.small {
		font-size: 12.5px;
	}

	.tiny {
		font-size: 11px;
	}

	code {
		padding: 1px 4px;
		border: 1px solid var(--line);
		border-radius: 4px;
		background: rgba(0, 0, 0, 0.35);
		font-family: var(--mono);
		font-size: 11.5px;
	}

	@media (max-width: 700px) {
		.row {
			flex-direction: column;
			align-items: stretch;
		}

		.row .btn {
			align-self: flex-end;
		}
	}
</style>
