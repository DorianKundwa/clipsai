import {
	PLATFORMS,
	aspectForPlatforms,
	type Aspect,
	type Destination,
	type Platform
} from '../video';

const STORAGE_KEY = 'clipsai.targets';

/**
 * Publishing destinations, shared by the studio, the exports strip and the
 * publish dialog, and remembered between visits. The IndiePost store calls
 * `sync` whenever accounts load, so nothing here fetches.
 */
class TargetStore {
	selected = $state<Platform[]>([]);
	/** Follow the platforms' preferred frame instead of the source ratio. */
	autoFrame = $state(true);

	/** Preferred frame for the selection; null while nothing is picked. */
	recommendedAspect = $derived<Aspect | null>(aspectForPlatforms(this.selected));

	/** False until the user picks; until then every linked account is targeted. */
	#chosen = false;

	constructor() {
		if (typeof localStorage === 'undefined') return;

		try {
			const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as {
				selected?: unknown;
				autoFrame?: unknown;
			} | null;

			const saved = stored?.selected;
			if (Array.isArray(saved)) {
				this.selected = PLATFORMS.filter((platform) => saved.includes(platform));
				this.#chosen = true;
			}
			if (typeof stored?.autoFrame === 'boolean') this.autoFrame = stored.autoFrame;
		} catch {
			// Unreadable storage: keep the defaults.
		}
	}

	#save(): void {
		if (typeof localStorage === 'undefined') return;

		try {
			localStorage.setItem(
				STORAGE_KEY,
				JSON.stringify({ selected: this.selected, autoFrame: this.autoFrame })
			);
		} catch {
			// Private mode or full quota: the choice still holds for this visit.
		}
	}

	/**
	 * Align with the accounts IndiePost reports. Before the user picks, every
	 * linked account is targeted; afterwards unlinked accounts drop out.
	 */
	sync(accounts: readonly Destination[]): void {
		const linked = new Set(
			accounts.filter((account) => account.connected).map((account) => account.platform)
		);

		this.selected = this.#chosen
			? this.selected.filter((platform) => linked.has(platform))
			: PLATFORMS.filter((platform) => linked.has(platform));
		this.#save();
	}

	toggle(platform: Platform): void {
		const picked = new Set(this.selected);
		if (picked.has(platform)) picked.delete(platform);
		else picked.add(platform);

		this.#chosen = true;
		this.selected = PLATFORMS.filter((entry) => picked.has(entry));
		this.#save();
	}

	setAutoFrame(value: boolean): void {
		this.autoFrame = value;
		this.#save();
	}
}

export const targets = new TargetStore();
