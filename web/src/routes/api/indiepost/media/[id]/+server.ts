import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { IndiePostError, deleteMedia, isConfigured } from '#lib/server/indiepost';
import { isSameOrigin } from '#lib/server/http';

/** Remove one uploaded file from the IndiePost workspace. */
export const DELETE: RequestHandler = async ({ params, request, url }) => {
	if (!isSameOrigin(request, url.origin)) {
		return json({ error: 'Cross-origin requests are not allowed.' }, { status: 403 });
	}

	if (!isConfigured()) {
		return json(
			{ error: 'IndiePost is not configured. Set INDIEPOST_API_KEY in the repository .env file.' },
			{ status: 503 }
		);
	}

	const mediaId = String(params.id ?? '').trim();
	if (!mediaId) {
		return json({ error: 'A media id is required.' }, { status: 400 });
	}

	try {
		await deleteMedia(mediaId);
		return json({ ok: true });
	} catch (error) {
		const status = error instanceof IndiePostError ? error.status : 502;
		const message = error instanceof Error ? error.message : 'Could not delete that media.';
		return json({ error: message }, { status });
	}
};
