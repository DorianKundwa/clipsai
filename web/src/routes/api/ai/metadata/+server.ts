import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { AIError, aiModel, generateMetadata, isAIConfigured } from '#lib/server/deepseek';
import { isSameOrigin } from '#lib/server/http';

/** Lets the UI disable the AI button instead of failing on click. */
export const GET: RequestHandler = () =>
	json(
		{ configured: isAIConfigured(), model: aiModel() },
		{ headers: { 'cache-control': 'no-store' } }
	);

export const POST: RequestHandler = async ({ request, url }) => {
	if (!isSameOrigin(request, url.origin)) {
		return json({ error: 'Cross-origin requests are not allowed.' }, { status: 403 });
	}

	if (!isAIConfigured()) {
		return json(
			{ error: 'DeepSeek is not configured. Add DEEPSEEK_API_KEY to the repository .env file.' },
			{ status: 503 }
		);
	}

	let body: Record<string, unknown>;
	try {
		body = (await request.json()) as Record<string, unknown>;
	} catch {
		return json({ error: 'Expected a JSON body.' }, { status: 400 });
	}

	const name = typeof body.name === 'string' ? body.name.trim() : '';
	if (!name) {
		return json({ error: 'A clip name is required to write metadata.' }, { status: 400 });
	}

	const platforms = Array.isArray(body.platforms)
		? body.platforms.map((platform) => String(platform)).filter(Boolean)
		: [];

	try {
		const metadata = await generateMetadata({
			name,
			start: Number(body.start) || 0,
			end: Number(body.end) || 0,
			aspect: String(body.aspect ?? 'source'),
			look: String(body.look ?? 'none'),
			platforms,
			brief: typeof body.brief === 'string' ? body.brief : '',
			existingCaption: typeof body.existingCaption === 'string' ? body.existingCaption : ''
		});

		return json(metadata, { headers: { 'cache-control': 'no-store' } });
	} catch (error) {
		const status = error instanceof AIError ? error.status : 502;
		const message = error instanceof Error ? error.message : 'Metadata generation failed.';
		return json({ error: message }, { status });
	}
};
