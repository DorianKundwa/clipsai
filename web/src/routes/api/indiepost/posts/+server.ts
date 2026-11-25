import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { IndiePostError, isConfigured, listPosts } from '#lib/server/indiepost';

const DAY_MS = 86_400_000;

function isoOffset(days: number): string {
	return new Date(Date.now() + days * DAY_MS).toISOString();
}

/**
 * Post groups in a window (default: the two weeks either side of now, so both
 * recent posts and anything still scheduled show up).
 */
export const GET: RequestHandler = async ({ url }) => {
	if (!isConfigured()) {
		return json({
			configured: false,
			posts: [],
			message: 'INDIEPOST_API_KEY is not set in the repository .env file.'
		});
	}

	const from = url.searchParams.get('from') || isoOffset(-14);
	const to = url.searchParams.get('to') || isoOffset(14);

	if (Number.isNaN(Date.parse(from)) || Number.isNaN(Date.parse(to))) {
		return json({ error: 'from and to must be ISO 8601 timestamps.' }, { status: 400 });
	}

	try {
		const posts = await listPosts(from, to);
		return json(
			{ configured: true, from, to, posts },
			{ headers: { 'cache-control': 'no-store' } }
		);
	} catch (error) {
		const status = error instanceof IndiePostError ? error.status : 502;
		const message = error instanceof Error ? error.message : 'Could not load IndiePost posts.';
		return json({ configured: true, from, to, posts: [], message }, { status });
	}
};
