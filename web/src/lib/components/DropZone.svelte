<script lang="ts">
import { goto } from '$app/navigation';
import { videoStore } from '#lib/stores/videoStore.svelte';
import { MAX_BYTES, formatBytes } from '#lib/video';

interface Props {
	title?: string;
	subtitle?: string;
	compact?: boolean;
}

let { title = 'Drop a video to begin', subtitle = '', compact = false }: Props = $props();

let draggingOver = $state(false);
let error = $state<string | null>(null);
let input = $state<HTMLInputElement | null>(null);

function accept(file: File | undefined): void {
	if (!file) return;

	const looksLikeVideo = file.type.startsWith('video/') || /\.(mp4|mov|m4v|webm|mkv|ogv)$/i.test(file.name);
	if (!looksLikeVideo) {
		error = `“${file.name}” is not a video file.`;
		return;
	}

	if (file.size > MAX_BYTES) {
		error = `That file is ${formatBytes(file.size)}. The browser editor is limited to 2 GB per clip.`;
		return;
	}

	error = null;
	videoStore.attach(file);
	goto('/studio');
}

function onDrop(event: DragEvent): void {
	event.preventDefault();
	draggingOver = false;
	accept(event.dataTransfer?.files?.[0]);
}

function onPick(event: Event): void {
	const target = event.currentTarget as HTMLInputElement;
	accept(target.files?.[0]);
	target.value = '';
}
</script>

<div
	class="drop"
	class:compact
	role="button"
	tabindex="0"
	data-over={draggingOver}
	onclick={() => input?.click()}
	onkeydown={(event) => {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			input?.click();
		}
	}}
	ondragover={(event) => {
		event.preventDefault();
		draggingOver = true;
	}}
	ondragleave={() => (draggingOver = false)}
	ondrop={onDrop}
>
	<span class="icon" aria-hidden="true">
		<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6">
			<path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" stroke-linecap="round" stroke-linejoin="round" />
			<path d="M4 15v3a2 2 0 002 2h12a2 2 0 002-2v-3" stroke-linecap="round" />
		</svg>
	</span>

	<div class="copy">
		<strong>{title}</strong>
		{#if subtitle}<span>{subtitle}</span>{/if}
	</div>

	<span class="hint mono">{compact ? 'MP4 · MOV · WEBM · MKV' : 'click to browse · or drag a file here'}</span>
</div>

{#if error}
	<p class="notice">{error}</p>
{/if}

<input
	bind:this={input}
	class="sr-only"
	type="file"
	accept="video/*,.mp4,.mov,.m4v,.webm,.mkv"
	onchange={onPick}
	tabindex="-1"
/>

<style>
	.drop {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 22px;
		border: 1px dashed var(--line-strong);
		border-radius: var(--radius);
		background: rgba(255, 255, 255, 0.02);
		cursor: pointer;
		transition: border-color 160ms ease, background 160ms ease;
	}

	.drop.compact {
		padding: 16px;
	}

	.drop:hover,
	.drop[data-over='true'] {
		border-color: rgba(215, 255, 62, 0.6);
		background: var(--accent-soft);
	}

	.icon {
		display: grid;
		place-items: center;
		flex: 0 0 auto;
		width: 44px;
		height: 44px;
		border: 1px solid var(--line);
		border-radius: 12px;
		background: rgba(0, 0, 0, 0.35);
		color: var(--accent);
	}

	.copy {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.copy strong {
		font-size: 15px;
		font-weight: 600;
	}

	.copy span {
		color: var(--muted);
		font-size: 13px;
	}

	.hint {
		margin-left: auto;
		color: var(--muted);
		font-size: 10.5px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		white-space: nowrap;
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}

	@media (max-width: 640px) {
		.hint {
			display: none;
		}
	}
</style>
