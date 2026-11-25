<script lang="ts">
	import { indiePost } from '#lib/stores/indiepost.svelte';
	import { targets } from '#lib/stores/targets.svelte';
	import { PLATFORM_LABELS, destinationHandle } from '#lib/video';

	interface Props {
		/** Chip strip for page headers; stacked rows for panels and dialogs. */
		variant?: 'rows' | 'chips';
	}

	let { variant = 'rows' }: Props = $props();
</script>

{#if indiePost.configured === false}
	<p class="hint">Add <code>INDIEPOST_API_KEY</code> to <code>.env</code> to link accounts.</p>
{:else if !indiePost.loaded}
	<p class="hint">{indiePost.error ?? 'Checking linked accounts…'}</p>
{:else if variant === 'chips'}
	<div class="chips">
		{#each indiePost.accounts as account (account.platform)}
			{@const on = targets.selected.includes(account.platform)}
			<button
				class="chip"
				data-on={account.connected}
				data-selected={on}
				aria-pressed={on}
				disabled={!account.connected}
				title={account.connected
					? 'Include or exclude this account'
					: 'Link this account in IndiePost'}
				onclick={() => targets.toggle(account.platform)}
			>
				<span class="tick" aria-hidden="true">{on ? '✓' : ''}</span>
				{PLATFORM_LABELS[account.platform]}
				<span class="handle mono">{destinationHandle(account)}</span>
			</button>
		{/each}
	</div>
{:else}
	<div class="rows">
		{#each indiePost.accounts as account (account.platform)}
			<button
				class="row"
				aria-pressed={targets.selected.includes(account.platform)}
				disabled={!account.connected}
				onclick={() => targets.toggle(account.platform)}
			>
				<span class="dot" data-on={account.connected}></span>
				<span class="name">{PLATFORM_LABELS[account.platform]}</span>
				<span class="handle mono">{destinationHandle(account)}</span>
			</button>
		{/each}
	</div>
{/if}

<style>
	.hint {
		color: var(--muted);
		font-size: 11.5px;
	}

	.hint code {
		font-family: var(--mono);
	}

	.rows {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 8px;
	}

	.row {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 1px 7px;
		align-items: center;
		padding: 8px 11px;
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		background: rgba(255, 255, 255, 0.02);
		text-align: left;
		cursor: pointer;
	}

	.row:disabled,
	.chip:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}

	.row:hover:not(:disabled),
	.chip:hover:not(:disabled) {
		border-color: var(--line-strong);
	}

	.row[aria-pressed='true'] {
		border-color: rgba(215, 255, 62, 0.5);
		background: var(--accent-soft);
	}

	.dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: rgba(255, 255, 255, 0.22);
	}

	.dot[data-on='true'] {
		background: var(--ok);
		box-shadow: 0 0 8px rgba(98, 224, 160, 0.6);
	}

	.name {
		font-size: 12.5px;
		font-weight: 600;
	}

	.handle {
		color: var(--muted);
	}

	.row .handle {
		grid-column: 2;
		overflow: hidden;
		font-size: 10px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.chips {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
	}

	.chip {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 3px 10px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.02);
		color: var(--muted);
		font-size: 12px;
		cursor: pointer;
	}

	.chip[data-on='true'] {
		border-color: rgba(98, 224, 160, 0.35);
		color: var(--text);
	}

	.chip[data-selected='true'] {
		border-color: rgba(215, 255, 62, 0.5);
		background: var(--accent-soft);
		color: var(--text);
	}

	.chip .handle {
		font-size: 10.5px;
	}

	.tick {
		width: 9px;
		color: var(--accent);
		font-size: 10px;
		line-height: 1;
	}

	@media (max-width: 520px) {
		.rows {
			grid-template-columns: minmax(0, 1fr);
		}
	}
</style>
