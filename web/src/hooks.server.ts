import type { Handle } from '@sveltejs/kit/hooks';
import { isolationHeaders } from '../isolation-headers.js';

/**
 * Cross-origin isolation on every SvelteKit response.
 *
 * Static assets are served before hooks run, so `server.js` (production) and the
 * Vite plugin (development) apply the same headers to those as well.
 */
export const handle: Handle = async ({ event, resolve }) => {
	const response = await resolve(event);

	for (const [name, value] of Object.entries(isolationHeaders)) {
		response.headers.set(name, value);
	}

	return response;
};
