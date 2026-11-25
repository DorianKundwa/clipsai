export type Look = 'none' | 'warm' | 'cool' | 'mono' | 'punch';
export type Aspect = 'source' | '9:16' | '1:1' | '16:9';

export interface TrimOptions {
	/** Seconds, relative to the start of the source file. */
	start: number;
	/** Seconds, relative to the start of the source file. */
	end: number;
	look: Look;
	aspect: Aspect;
}

export interface LookPreset {
	id: Look;
	label: string;
	hint: string;
}

export const LOOKS: LookPreset[] = [
	{ id: 'none', label: 'Original', hint: 'No colour change' },
	{ id: 'warm', label: 'Warm', hint: 'Golden skin tones' },
	{ id: 'cool', label: 'Cool', hint: 'Teal shadows' },
	{ id: 'punch', label: 'Punch', hint: 'More contrast + saturation' },
	{ id: 'mono', label: 'Mono', hint: 'Desaturated' }
];

export interface AspectPreset {
	id: Aspect;
	label: string;
	hint: string;
	/** width / height, used for the preview crop guide. */
	ratio: number | null;
}

export const ASPECTS: AspectPreset[] = [
	{ id: 'source', label: 'Source', hint: 'Keep the original framing', ratio: null },
	{ id: '9:16', label: '9:16', hint: 'Reels, Shorts, TikTok', ratio: 9 / 16 },
	{ id: '1:1', label: '1:1', hint: 'Square feed post', ratio: 1 },
	{ id: '16:9', label: '16:9', hint: 'YouTube landscape', ratio: 16 / 9 }
];

export const MAX_BYTES = 2 * 1024 * 1024 * 1024;

/** Destinations IndiePost can publish to, in picker order. */
export const PLATFORMS = ['youtube', 'tiktok', 'instagram', 'facebook'] as const;
export type Platform = (typeof PLATFORMS)[number];

export const PLATFORM_LABELS: Record<Platform, string> = {
	youtube: 'YouTube',
	tiktok: 'TikTok',
	instagram: 'Instagram',
	facebook: 'Facebook'
};

/** A supported destination and whether an account is linked to it. */
export interface Destination {
	platform: Platform;
	connected: boolean;
	username: string | null;
}

/** `@handle`, `linked` or `not linked` — one wording for every picker. */
export function destinationHandle(destination: Destination): string {
	if (!destination.connected) return 'not linked';
	return destination.username ? `@${destination.username}` : 'linked';
}

/** Destinations that want a vertical frame whatever the YouTube format is. */
const VERTICAL_PLATFORMS: readonly string[] = ['tiktok', 'instagram', 'facebook'];

/**
 * Preferred frame for a set of destinations. Vertical wins in a mixed selection
 * because TikTok, Reels and Facebook crop 16:9 badly; only a YouTube long-form
 * post asks for landscape.
 */
export function aspectForPlatforms(
	platforms: readonly Platform[],
	youtubeFormat: 'short' | 'long' = 'short'
): Aspect | null {
	if (platforms.length === 0) return null;
	const vertical = platforms.some((platform) => VERTICAL_PLATFORMS.includes(platform));
	return vertical || youtubeFormat !== 'long' ? '9:16' : '16:9';
}

export function formatTime(seconds: number): string {
	if (!Number.isFinite(seconds) || seconds < 0) return '0:00.000';
	const minutes = Math.floor(seconds / 60);
	const rest = seconds - minutes * 60;
	return `${minutes}:${rest.toFixed(3).padStart(6, '0')}`;
}

export function formatDuration(seconds: number): string {
	if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
	const total = Math.round(seconds);
	const minutes = Math.floor(total / 60);
	return `${minutes}:${String(total % 60).padStart(2, '0')}`;
}

export function formatBytes(bytes: number): string {
	if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB'];
	const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
	const value = bytes / 1024 ** exponent;
	return `${value >= 10 || exponent === 0 ? Math.round(value) : value.toFixed(1)} ${units[exponent]}`;
}
