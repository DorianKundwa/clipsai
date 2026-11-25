import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { IndiePostError, isConfigured, listAccounts } from '#lib/server/indiepost';

/** Linked accounts come from IndiePost, never from the client. */
export const GET: RequestHandler = async () => {
	if (!isConfigured()) {
		return json({
			configured: false,
			workspace: null,
			accounts: [],
			message: 'INDIEPOST_API_KEY is not set in the repository .env file.'
		});
	}

	try {
		const result = await listAccounts();
		return json(
			{ configured: true, ...result },
			{ headers: { 'cache-control': 'no-store' } }
		);
	} catch (error) {
		const status = error instanceof IndiePostError ? error.status : 502;
		const message = error instanceof Error ? error.message : 'Could not load IndiePost accounts.';
		return json({ configured: true, workspace: null, accounts: [], message }, { status });
	}
};
