import { defineEnvVars } from '@sveltejs/kit/env';

/**
 * Server-side environment for the web app.
 *
 * SvelteKit 3 replaced `$env/dynamic/private` with declared variables: anything
 * listed here is importable from `$app/env/private` (server-only, never sent to
 * the browser). Values come from the process environment, or from the `.env`
 * file in `env.dir` — which points at the repository root so the web app and
 * the Python backend share one `.env`.
 */
export const variables = defineEnvVars({
	DEEPSEEK_API_KEY: {
		description: 'DeepSeek API key used to write clip metadata.',
		schema: (value: string | undefined) => (value ?? '').trim()
	},
	DEEPSEEK_BASE_URL: {
		description: 'DeepSeek API origin.',
		schema: (value: string | undefined) =>
			(value ?? '').trim().replace(/\/+$/, '') || 'https://api.deepseek.com'
	},
	DEEPSEEK_MODEL: {
		description: 'DeepSeek chat model.',
		schema: (value: string | undefined) => (value ?? '').trim() || 'deepseek-chat'
	},
	INDIEPOST_API_KEY: {
		description: 'IndiePost API key (ip_…) used to publish to linked accounts.',
		schema: (value: string | undefined) => (value ?? '').trim()
	},
	INDIEPOST_BASE_URL: {
		description: 'IndiePost origin. Keep the www host; the apex URL redirects.',
		schema: (value: string | undefined) =>
			(value ?? '').trim().replace(/\/+$/, '') || 'https://www.indiepost.app'
	}
});
