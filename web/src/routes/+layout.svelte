<script lang="ts">
import '../app.css';
import { page } from '$app/state';
import { videoStore } from '#lib/stores/videoStore.svelte';

let { children } = $props();

const nav = [
	{ href: '/', label: 'Overview' },
	{ href: '/pipeline', label: 'Pipeline' },
	{ href: '/studio', label: 'Studio' },
	{ href: '/exports', label: 'Exports' },
	{ href: '/library', label: 'Library' }
];

const isActive = (href: string) =>
	href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
</script>

<svelte:head>
	<meta name="theme-color" content="#08090b" />
</svelte:head>

<header class="topbar">
	<div class="shell bar">
		<a class="brand" href="/">
			<span class="mark" aria-hidden="true">
				<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7">
					<rect x="3" y="6" width="12" height="12" rx="2.5" />
					<path d="M15 11l6-3.5v9L15 13z" fill="currentColor" stroke="none" />
				</svg>
			</span>
			<span>ClipsAI <em>Studio</em></span>
		</a>

		<nav aria-label="Primary">
			{#each nav as item (item.href)}
				<a
					href={item.href}
					class:active={isActive(item.href)}
					aria-current={isActive(item.href) ? 'page' : undefined}
				>
					{item.label}
					{#if item.href === '/exports' && videoStore.activeJobs > 0}
						<span class="count mono">{videoStore.activeJobs}</span>
					{/if}
				</a>
			{/each}
		</nav>
	</div>
</header>

<main class="shell">
	{@render children()}
</main>

<style>
	.topbar {
		position: sticky;
		top: 0;
		z-index: 20;
		border-bottom: 1px solid var(--line);
		background: rgba(8, 9, 11, 0.78);
		backdrop-filter: blur(14px) saturate(140%);
	}

	.bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 20px;
		height: 60px;
	}

	.brand {
		display: inline-flex;
		align-items: center;
		gap: 10px;
		font-size: 14.5px;
		font-weight: 600;
		letter-spacing: -0.01em;
	}

	.brand em {
		color: var(--muted);
		font-style: normal;
		font-weight: 500;
	}

	.mark {
		display: grid;
		place-items: center;
		width: 28px;
		height: 28px;
		border-radius: 8px;
		background: var(--accent);
		color: #0a0b0d;
	}

	nav {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	nav a {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 7px 13px;
		border-radius: 999px;
		color: var(--muted);
		font-size: 13.5px;
		transition: color 140ms ease, background 140ms ease;
	}

	nav a:hover {
		color: var(--text);
		background: rgba(255, 255, 255, 0.04);
	}

	nav a.active {
		color: var(--text);
		background: rgba(255, 255, 255, 0.07);
	}

	.count {
		padding: 0 6px;
		border-radius: 999px;
		background: var(--accent);
		color: #0a0b0d;
		font-size: 10px;
		font-weight: 700;
	}

	@media (max-width: 560px) {
		.brand em {
			display: none;
		}
		nav a {
			padding: 7px 10px;
			font-size: 12.5px;
		}
	}
</style>
