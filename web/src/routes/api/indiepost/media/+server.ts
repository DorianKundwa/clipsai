import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { IndiePostError, isConfigured, listMedia } from '#lib/server/indiepost';

/** Media already stored by IndiePost; its ids can be reused for new posts. */
export const GET: RequestHandler = async () => {
	if (!isConfigured()) {
		return json({
			configured: false,
			items: [],
			message: 'INDIEPOST_API_KEY is not set in the repository .env file.'
		});
	}

	try {
		const items = await listMedia();
		return json(
			{ configured: true, items },
			{ headers: { 'cache-control': 'no-store' } }
		);
	} catch (error) {
		const status = error instanceof IndiePostError ? error.status : 502;
		const message = error instanceof Error ? error.message : 'Could not load IndiePost media.';
		return json({ configured: true, items: [], message }, { status });
	}
};
