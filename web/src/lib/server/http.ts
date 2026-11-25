/**
 * Same-origin guard for state-changing endpoints.
 *
 * SvelteKit's built-in CSRF check covers form-encoded posts, but not JSON
 * bodies. Both spend money (DeepSeek) or publish content (IndiePost), so they
 * check the Origin header themselves. A missing Origin means a non-browser
 * client (curl, tests) and is allowed; a browser always sends one.
 */
export function isSameOrigin(request: Request, origin: string): boolean {
	const header = request.headers.get('origin');
	if (!header) return true;

	try {
		return new URL(header).origin === origin;
	} catch {
		return false;
	}
}
