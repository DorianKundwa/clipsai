import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import {
	IndiePostError,
	MAX_UPLOAD_BYTES,
	isConfigured,
	publishVideo,
	validatePublishRequest
} from '#lib/server/indiepost';
import { isSameOrigin } from '#lib/server/http';

/** Publish details (platforms, caption, options) as base64url JSON. */
const META_HEADER = 'x-clipsai-publish';

function readMetadata(header: string | null): Record<string, unknown> | null {
	if (!header) return null;
	try {
		const text = Buffer.from(header, 'base64url').toString('utf8');
		const parsed: unknown = JSON.parse(text);
		return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null;
	} catch {
		return null;
	}
}

/** Header values are latin-1, so the browser percent-encodes the file name. */
function decodeName(header: string | null): string {
	if (!header) return 'clip.mp4';
	try {
		return decodeURIComponent(header).slice(0, 200) || 'clip.mp4';
	} catch {
		return 'clip.mp4';
	}
}

/**
 * Accepts the rendered clip as a raw request body and streams it to IndiePost.
 *
 * Nothing is buffered: the size is checked from the headers before a byte of the
 * body is read, and the publish details travel in a header so the body stays the
 * clip itself instead of a multipart copy.
 */
export const POST: RequestHandler = async ({ request, url }) => {
	if (!isSameOrigin(request, url.origin)) {
		return json({ error: 'Cross-origin requests are not allowed.' }, { status: 403 });
	}

	if (!isConfigured()) {
		return json(
			{ error: 'IndiePost is not configured. Set INDIEPOST_API_KEY in the repository .env file.' },
			{ status: 503 }
		);
	}

	const declared = Number(request.headers.get('x-clip-size'));
	if (!Number.isSafeInteger(declared) || declared <= 0) {
		return json({ error: 'Expected the clip size in the x-clip-size header.' }, { status: 411 });
	}

	if (declared > MAX_UPLOAD_BYTES) {
		return json({ error: 'IndiePost accepts files up to 2 GB.' }, { status: 413 });
	}

	const contentLength = Number(request.headers.get('content-length'));
	if (Number.isFinite(contentLength) && contentLength > 0 && contentLength !== declared) {
		return json({ error: 'The upload size did not match the clip size.' }, { status: 400 });
	}

	const body = request.body;
	if (!body) {
		return json({ error: 'No video file was uploaded.' }, { status: 400 });
	}

	const metadata = readMetadata(request.headers.get(META_HEADER));
	if (!metadata) {
		return json({ error: 'The publish details are missing or unreadable.' }, { status: 400 });
	}

	try {
		const payload = validatePublishRequest(metadata);
		const result = await publishVideo(
			{
				name: decodeName(request.headers.get('x-clip-name')),
				mimeType: request.headers.get('content-type') || 'video/mp4',
				size: declared,
				stream: body
			},
			payload
		);
		return json(result, { headers: { 'cache-control': 'no-store' } });
	} catch (error) {
		const status = error instanceof IndiePostError ? error.status : 502;
		const message = error instanceof Error ? error.message : 'Publishing failed.';
		return json({ error: message }, { status });
	}
};
