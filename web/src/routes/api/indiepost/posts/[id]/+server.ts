import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { IndiePostError, deletePost, isConfigured } from '#lib/server/indiepost';
import { isSameOrigin } from '#lib/server/http';

/** Delete a post group, removing it from every platform it was sent to. */
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

	const postGroupId = String(params.id ?? '').trim();
	if (!postGroupId) {
		return json({ error: 'A post group id is required.' }, { status: 400 });
	}

	try {
		await deletePost(postGroupId);
		return json({ ok: true });
	} catch (error) {
		const status = error instanceof IndiePostError ? error.status : 502;
		const message = error instanceof Error ? error.message : 'Could not delete that post.';
		return json({ error: message }, { status });
	}
};
