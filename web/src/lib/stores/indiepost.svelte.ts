import { PLATFORMS, type Destination, type Platform } from '#lib/video';
import { targets } from './targets.svelte';

type RawAccount = { platform?: unknown; connected?: unknown; username?: unknown };

/** One row per supported destination, linked or not, in picker order. */
function normalizeAccounts(raw: RawAccount[]): Destination[] {
	return PLATFORMS.map((platform) => {
		const match = raw.find((account) => account.platform === platform);
		return {
			platform,
			connected: match?.connected === true,
			username: typeof match?.username === 'string' ? match.username : null
		};
	});
}

/**
 * Linked IndiePost accounts, fetched once and shared by the exports list, the
 * studio panel and the publish dialog. The server holds the key; this store
 * only sees platform names and usernames.
 */
class IndiePostStore {
	loaded = $state(false);
	loading = $state(false);
	configured = $state<boolean | null>(null);
	workspace = $state<{ id: string; name: string } | null>(null);
	accounts = $state<Destination[]>([]);
	/** Server-supplied explanation, e.g. a rejected key. */
	message = $state<string | null>(null);
	error = $state<string | null>(null);

	connected = $derived(this.accounts.filter((account) => account.connected));

	/** Shared so two components mounting at once cannot read a half-filled store. */
	#inflight: Promise<void> | null = null;

	load(force = false): Promise<void> {
		if (this.#inflight) return this.#inflight;
		if (this.loaded && !force) return Promise.resolve();

		this.#inflight = this.#fetch().finally(() => {
			this.#inflight = null;
		});

		return this.#inflight;
	}

	async #fetch(): Promise<void> {
		this.loading = true;
		this.error = null;

		try {
			const response = await fetch('/api/indiepost/accounts');
			const data = await response.json();
			const configured = data.configured !== false;

			this.configured = configured;
			this.workspace = data.workspace ?? null;
			this.message = data.message ?? null;

			if (configured) {
				this.accounts = normalizeAccounts(Array.isArray(data.accounts) ? data.accounts : []);
				// One place keeps the publishing selection aligned with what is linked.
				targets.sync(this.accounts);
			} else {
				this.accounts = [];
			}

			this.loaded = true;
		} catch {
			this.error = 'Could not reach the studio server.';
		} finally {
			this.loading = false;
		}
	}
}

export const indiePost = new IndiePostStore();
