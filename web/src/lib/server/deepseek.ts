import { DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL } from '$app/env/private';

/**
 * Metadata generation for an exported clip, via DeepSeek's chat API.
 *
 * DeepSeek is text-only, so the model works from facts the app already knows
 * about the export (file name, cut length, aspect, look, targets) plus an
 * optional note from the editor. It is instructed not to invent details.
 */

export interface MetadataInput {
	name: string;
	start: number;
	end: number;
	aspect: string;
	look: string;
	platforms: string[];
	brief?: string;
	existingCaption?: string;
}

export interface GeneratedMetadata {
	title: string;
	caption: string;
	hashtags: string[];
	model: string;
}

export class AIError extends Error {
	readonly status: number;

	constructor(message: string, status = 502) {
		super(message);
		this.name = 'AIError';
		this.status = status;
	}
}

const MAX_TAGS = 8;

export function isAIConfigured(): boolean {
	return DEEPSEEK_API_KEY.length > 0;
}

export function aiModel(): string {
	return DEEPSEEK_MODEL;
}

const SYSTEM_PROMPT = `You write publishing metadata for short-form video clips.

You receive facts about one exported clip: its file name, trimmed length, aspect
ratio, colour look, the platforms it will be posted to, and an optional note from
the editor describing the content.

Rules:
- title: one line for YouTube, at most 90 characters. No hashtags, no emoji, no
  quotation marks, no clickbait. It must make sense on its own. Never headline
  technical facts (duration, aspect ratio, colour look): those describe the file,
  not the story. Prefer the editor's note, then the file name, but never copy
  the note verbatim: condense it into a headline with no trailing period.
- caption: one or two sentences usable on TikTok and Instagram, at most 220
  characters. No hashtags, no emoji, plain text, no leading label. If an existing
  caption is supplied, keep its intent and improve it instead of starting over.
- hashtags: 6 to 8 lowercase tags, letters/digits/underscore only, without '#'.
  Use real, widely searched words. No invented compounds, no spelled-out numbers,
  no tags about the aspect ratio or file format.
- Ground every word in the supplied facts or the editor's note. Never invent
  people, brands, places, events or claims that are not supported by them.
- Match the tone to the listed platforms; keep it neutral when the facts are thin.

Respond with JSON only, exactly this shape:
{"title":"...","caption":"...","hashtags":["..."]}`;

function text(value: unknown, limit: number): string {
	return typeof value === 'string' ? value.trim().slice(0, limit) : '';
}

/** Strips ```json fences some models wrap around JSON. */
function unwrap(content: string): string {
	const trimmed = content.trim();
	const fenced = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
	return fenced ? fenced[1] : trimmed;
}

function normalize(raw: unknown): { title: string; caption: string; hashtags: string[] } {
	const record = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
	const title = text(record.title, 100).replace(/[.。]+$/, '');
	const caption = text(record.caption, 700);

	const tags = Array.isArray(record.hashtags) ? record.hashtags : [];
	const hashtags = [
		...new Set(
			tags
				.map((tag) => String(tag).trim().replace(/^#+/, '').toLowerCase())
				.filter((tag) => /^[a-z0-9_]{2,30}$/.test(tag))
		)
	].slice(0, MAX_TAGS);

	if (!title || !caption) {
		throw new AIError('DeepSeek returned incomplete metadata. Try again.', 502);
	}

	return { title, caption, hashtags };
}

export async function generateMetadata(input: MetadataInput): Promise<GeneratedMetadata> {
	if (!isAIConfigured()) {
		throw new AIError(
			'DeepSeek is not configured. Add DEEPSEEK_API_KEY to the repository .env file.',
			503
		);
	}

	const facts = {
		file: input.name,
		length_seconds: Number(Math.max(0, input.end - input.start).toFixed(2)),
		aspect_ratio: input.aspect,
		colour_look: input.look,
		platforms: input.platforms,
		editor_note: input.brief?.trim() || null,
		existing_caption: input.existingCaption?.trim() || null
	};

	let response: Response;
	try {
		response = await fetch(`${DEEPSEEK_BASE_URL}/chat/completions`, {
			method: 'POST',
			headers: {
				Authorization: `Bearer ${DEEPSEEK_API_KEY}`,
				'Content-Type': 'application/json'
			},
			body: JSON.stringify({
				model: DEEPSEEK_MODEL,
				messages: [
					{ role: 'system', content: SYSTEM_PROMPT },
					{ role: 'user', content: JSON.stringify(facts) }
				],
				response_format: { type: 'json_object' },
				temperature: 0.7,
				max_tokens: 600
			}),
			signal: AbortSignal.timeout(45_000)
		});
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		throw new AIError(
			message.includes('timeout') || message.includes('aborted')
				? 'DeepSeek took too long to answer. Try again.'
				: `Could not reach DeepSeek: ${message}`
		);
	}

	const body = await response.text();

	if (response.status === 401 || response.status === 403) {
		throw new AIError('DeepSeek rejected the API key. Check DEEPSEEK_API_KEY.', 401);
	}

	if (!response.ok) {
		throw new AIError(`DeepSeek returned HTTP ${response.status}: ${body.trim().slice(0, 200)}`);
	}

	let content: unknown;
	try {
		const parsed = JSON.parse(body) as {
			choices?: Array<{ message?: { content?: string } }>;
		};
		content = parsed.choices?.[0]?.message?.content;
	} catch {
		throw new AIError('DeepSeek returned a response that was not JSON.');
	}

	if (typeof content !== 'string' || !content.trim()) {
		throw new AIError('DeepSeek returned an empty response.');
	}

	let metadata: unknown;
	try {
		metadata = JSON.parse(unwrap(content));
	} catch {
		throw new AIError('DeepSeek did not return usable metadata. Try again.');
	}

	return { ...normalize(metadata), model: DEEPSEEK_MODEL };
}
