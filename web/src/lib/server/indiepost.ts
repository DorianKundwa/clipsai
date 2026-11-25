import { INDIEPOST_API_KEY, INDIEPOST_BASE_URL } from '$app/env/private';

/**
 * Server-side IndiePost client.
 *
 * The API key never leaves the server: the browser posts a rendered clip to
 * /api/indiepost/publish and this module talks to IndiePost with
 * `Authorization: Bearer ip_…` on every request.
 *
 * Flow: POST /media (init) -> PUT upload.url -> POST /posts.
 */

import { PLATFORMS, type Platform } from '#lib/video';

export { PLATFORMS };
export type { Platform };

export const TIKTOK_PRIVACY = [
	'PUBLIC_TO_EVERYONE',
	'MUTUAL_FOLLOW_FRIENDS',
	'FOLLOWER_OF_CREATOR',
	'SELF_ONLY'
] as const;

export const MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024; // IndiePost limit

export interface AccountInfo {
	platform: string;
	connected: boolean;
	username: string | null;
}

export interface WorkspaceInfo {
	id: string;
	name: string;
}

export interface AccountsResult {
	workspace: WorkspaceInfo | null;
	accounts: AccountInfo[];
}

export interface MediaItem {
	mediaId: string;
	filename: string;
	mime: string;
	size: number;
	inUse: boolean;
}

export interface PostItem {
	platform: string;
	status: string;
	format: string | null;
	externalPostId: string | null;
	postedAt: string | null;
}

export interface PostGroup {
	postGroupId: string;
	status: string;
	scheduledAt: string | null;
	platforms: string[];
	posts: PostItem[];
}

export interface PublishRequest {
	platforms: Platform[];
	caption: string;
	when: string;
	youtubeTitle: string;
	youtubeFormat: 'short' | 'long';
	tiktokPrivacy: (typeof TIKTOK_PRIVACY)[number];
	aiGenerated: boolean;
	idempotencyKey: string;
}

export interface PublishResult {
	mediaId: string | null;
	platforms: Platform[];
	post: unknown;
	links: string[];
}

/** Raw, untrusted input as it arrives from the browser. */
export interface PublishInput {
	platforms?: unknown;
	caption?: unknown;
	when?: unknown;
	youtubeTitle?: unknown;
	youtubeFormat?: unknown;
	tiktokPrivacy?: unknown;
	aiGenerated?: unknown;
	idempotencyKey?: unknown;
}

/** A clip on its way to IndiePost: metadata plus the body, never buffered. */
export interface ClipUpload {
	name: string;
	mimeType: string;
	size: number;
	stream: ReadableStream<Uint8Array>;
}

export class IndiePostError extends Error {
	readonly status: number;

	constructor(message: string, status = 502) {
		super(message);
		this.name = 'IndiePostError';
		this.status = status;
	}
}

export function isConfigured(): boolean {
	return INDIEPOST_API_KEY.length > 0;
}

function endpoint(path: string): string {
	return `${INDIEPOST_BASE_URL}/api/v1${path.startsWith('/') ? path : `/${path}`}`;
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
	if (!isConfigured()) {
		throw new IndiePostError(
			'IndiePost is not configured. Set INDIEPOST_API_KEY in the repository .env file.',
			503
		);
	}

	let response: Response;
	try {
		response = await fetch(endpoint(path), {
			...init,
			headers: {
				Authorization: `Bearer ${INDIEPOST_API_KEY}`,
				Accept: 'application/json',
				...(init.headers as Record<string, string> | undefined)
			}
		});
	} catch (error) {
		throw new IndiePostError(
			`Could not reach IndiePost: ${error instanceof Error ? error.message : String(error)}`
		);
	}

	const body = await response.text();

	if (response.status === 401 || response.status === 403) {
		throw new IndiePostError(
			`IndiePost rejected the API key (HTTP ${response.status}). Create a new key in IndiePost → Settings → API keys.`,
			401
		);
	}

	if (!response.ok) {
		throw new IndiePostError(
			`IndiePost returned HTTP ${response.status}: ${body.trim().slice(0, 300)}`
		);
	}

	if (!body.trim()) return {} as T;

	try {
		return JSON.parse(body) as T;
	} catch {
		throw new IndiePostError('IndiePost returned a response that was not JSON.');
	}
}

/** Accounts of the default workspace, flattened for the picker. */
export async function listAccounts(): Promise<AccountsResult> {
	const data = await api<{ workspaces?: unknown }>('/accounts');
	const workspaces = Array.isArray(data.workspaces) ? data.workspaces : [];
	const workspace =
		workspaces.find((entry) => (entry as { isDefault?: boolean })?.isDefault) ?? workspaces[0];

	if (!workspace || typeof workspace !== 'object') {
		return { workspace: null, accounts: [] };
	}

	const record = workspace as {
		id?: string;
		name?: string;
		accounts?: Array<{ platform?: string; connected?: boolean; username?: string }>;
	};

	return {
		workspace: record.id ? { id: String(record.id), name: String(record.name ?? 'Default') } : null,
		accounts: (record.accounts ?? [])
			.filter((account) => typeof account?.platform === 'string')
			.map((account) => ({
				platform: String(account.platform),
				connected: account.connected === true,
				username: account.username ? String(account.username) : null
			}))
	};
}

function asRecord(value: unknown): Record<string, unknown> {
	return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

/** Media already stored by IndiePost, newest first as the API returns them. */
export async function listMedia(): Promise<MediaItem[]> {
	const data = await api<{ items?: unknown }>('/media');
	const items = Array.isArray(data.items) ? data.items : [];

	return items
		.map((entry) => {
			const item = asRecord(entry);
			return {
				mediaId: String(item.mediaId ?? item.id ?? ''),
				filename: String(item.filename ?? ''),
				mime: String(item.mime ?? ''),
				size: Number(item.size ?? 0),
				inUse: item.inUse === true
			};
		})
		.filter((item) => item.mediaId.length > 0);
}

export async function deleteMedia(mediaId: string): Promise<void> {
	await api(`/media/${encodeURIComponent(mediaId)}`, { method: 'DELETE' });
}

/** Finalize an upload: IndiePost serves the object only after this call. */
export async function confirmMedia(mediaId: string): Promise<void> {
	await api('/media/confirm', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ mediaId })
	});
}

function toPostItem(entry: unknown): PostItem {
	const post = asRecord(entry);
	return {
		platform: String(post.platform ?? ''),
		status: String(post.status ?? ''),
		format: post.format ? String(post.format) : null,
		externalPostId: post.externalPostId ? String(post.externalPostId) : null,
		postedAt: post.postedAt ? String(post.postedAt) : null
	};
}

function toPostGroup(entry: unknown): PostGroup {
	const group = asRecord(entry);
	return {
		postGroupId: String(group.postGroupId ?? group.id ?? ''),
		status: String(group.status ?? ''),
		scheduledAt: group.scheduledAt ? String(group.scheduledAt) : null,
		platforms: Array.isArray(group.platforms) ? group.platforms.map(String) : [],
		posts: Array.isArray(group.posts) ? group.posts.map(toPostItem) : []
	};
}

/** Post groups in a time window (ISO 8601 timestamps). */
export async function listPosts(from: string, to: string): Promise<PostGroup[]> {
	const query = new URLSearchParams({ from, to });
	const data = await api<{ posts?: unknown }>(`/posts?${query.toString()}`);
	const posts = Array.isArray(data.posts) ? data.posts : [];
	return posts.map(toPostGroup).filter((group) => group.postGroupId.length > 0);
}

export async function getPost(postGroupId: string): Promise<PostGroup> {
	return toPostGroup(await api(`/posts/${encodeURIComponent(postGroupId)}`));
}

export async function deletePost(postGroupId: string): Promise<void> {
	await api(`/posts/${encodeURIComponent(postGroupId)}`, { method: 'DELETE' });
}

function buildPostPayload(
	mediaIds: string[],
	request: PublishRequest
): Record<string, unknown> {
	const payload: Record<string, unknown> = {
		mediaIds,
		platforms: request.platforms,
		caption: request.caption.trim(),
		when: request.when || 'now',
		idempotencyKey: request.idempotencyKey
	};

	if (request.platforms.includes('youtube')) {
		payload.youtube = {
			title: request.youtubeTitle.trim().slice(0, 100),
			format: request.youtubeFormat,
			aiGenerated: request.aiGenerated
		};
	}

	if (request.platforms.includes('tiktok')) {
		payload.tiktok = {
			privacyLevel: request.tiktokPrivacy,
			aiGenerated: request.aiGenerated
		};
	}

	if (request.platforms.includes('instagram')) {
		payload.instagram = { format: 'reel', aiGenerated: request.aiGenerated };
	}

	if (request.platforms.includes('facebook')) {
		payload.facebook = { format: 'reel', aiGenerated: request.aiGenerated };
	}

	return payload;
}

/** Best-effort collection of post URLs / ids from the create-post response. */
function collectLinks(node: unknown, found: string[] = []): string[] {
	if (Array.isArray(node)) {
		for (const item of node) collectLinks(item, found);
		return found;
	}
	if (!node || typeof node !== 'object') return found;

	for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
		if (
			['postUrl', 'permalink', 'externalPostId', 'externalId', 'url'].includes(key) &&
			(typeof value === 'string' || typeof value === 'number')
		) {
			found.push(String(value));
		} else {
			collectLinks(value, found);
		}
	}

	return [...new Set(found)];
}

async function uploadStream(uploadUrl: string, upload: ClipUpload): Promise<void> {
	let response: Response;
	try {
		response = await fetch(uploadUrl, {
			method: 'PUT',
			// The signed URL is pre-authorized: no Bearer header here.
			headers: { 'Content-Type': upload.mimeType },
			// Streaming needs half-duplex; the bytes are forwarded as they arrive
			// instead of being copied into a second buffer.
			body: upload.stream,
			duplex: 'half'
		} as RequestInit & { duplex: 'half' });
	} catch (error) {
		throw new IndiePostError(
			`Uploading the clip failed: ${error instanceof Error ? error.message : String(error)}`
		);
	}

	if (!response.ok) {
		throw new IndiePostError(`The media upload was rejected (HTTP ${response.status}).`);
	}
}

/** Upload one video and create the post group for the selected platforms. */
export async function publishVideo(
	file: ClipUpload,
	request: PublishRequest
): Promise<PublishResult> {
	const mimeType = file.mimeType || 'video/mp4';

	const init = await api<{
		media?: { id?: string };
		mediaId?: string;
		id?: string;
		upload?: { url?: string } | string;
	}>('/media', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ filename: file.name, mimeType, size: file.size })
	});

	const uploadUrl =
		typeof init.upload === 'string' ? init.upload : (init.upload?.url ?? '');
	const mediaId = init.media?.id ?? init.mediaId ?? init.id ?? null;

	if (!uploadUrl || !mediaId) {
		throw new IndiePostError('IndiePost did not return both a media id and an upload URL.');
	}

	await uploadStream(uploadUrl, file);
	// Documented step three: the object is not usable until IndiePost confirms it.
	await confirmMedia(String(mediaId));

	const payload = buildPostPayload([String(mediaId)], request);
	const post = await api<Record<string, unknown>>('/posts', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			// Sent both as a header and in the body so a retry cannot double-post.
			'Idempotency-Key': request.idempotencyKey
		},
		body: JSON.stringify(payload)
	});

	return {
		mediaId: String(mediaId),
		platforms: request.platforms,
		post,
		links: collectLinks(post)
	};
}

/** Validation shared by the endpoint and (by copy) the Python publisher. */
function normalizePlatforms(value: unknown): string[] {
	let list: unknown[] = [];

	if (Array.isArray(value)) {
		list = value;
	} else if (typeof value === 'string') {
		const text = value.trim();
		if (text.startsWith('[')) {
			try {
				const parsed: unknown = JSON.parse(text);
				list = Array.isArray(parsed) ? parsed : [];
			} catch {
				list = [];
			}
		} else {
			list = text.split(',');
		}
	}

	const names = list.map((platform) => String(platform).toLowerCase().trim()).filter(Boolean);
	return [...new Set(names)];
}

export function validatePublishRequest(input: PublishInput): PublishRequest {
	const platforms = normalizePlatforms(input.platforms);

	if (platforms.length === 0) throw new IndiePostError('Select at least one platform.', 400);

	for (const platform of platforms) {
		if (platform === 'x') {
			throw new IndiePostError('X (Twitter) is not available through the IndiePost API.', 400);
		}
		if (!(PLATFORMS as readonly string[]).includes(platform)) {
			throw new IndiePostError(`Unknown platform "${platform}".`, 400);
		}
	}

	const youtubeTitle = String(input.youtubeTitle ?? '').trim();
	if (platforms.includes('youtube')) {
		if (!youtubeTitle) {
			throw new IndiePostError('YouTube needs a title.', 400);
		}
		if (youtubeTitle.length > 100) {
			throw new IndiePostError('YouTube titles are limited to 100 characters.', 400);
		}
	}

	const youtubeFormat = input.youtubeFormat === 'long' ? 'long' : 'short';
	const tiktokPrivacy = (TIKTOK_PRIVACY as readonly string[]).includes(
		String(input.tiktokPrivacy)
	)
		? (input.tiktokPrivacy as PublishRequest['tiktokPrivacy'])
		: 'PUBLIC_TO_EVERYONE';

	return {
		platforms: platforms as Platform[],
		caption: String(input.caption ?? '').slice(0, 2200),
		when: String(input.when ?? 'now').trim() || 'now',
		youtubeTitle,
		youtubeFormat,
		tiktokPrivacy,
		aiGenerated: input.aiGenerated === true,
		idempotencyKey: String(input.idempotencyKey ?? '').slice(0, 120)
	};
}
