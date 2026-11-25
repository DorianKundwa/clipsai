import { createServer } from 'node:http';
import { isolationHeaders } from './isolation-headers.js';

/**
 * adapter-node's own entry point does not let us touch responses, and SvelteKit
 * serves static assets before `handle` runs — so `/ffmpeg/*` would ship without
 * CORP and COEP would block the worker. Setting the headers on the raw response
 * first covers pages, endpoints and static files alike.
 */

// adapter-node derives the request origin from the socket protocol, defaulting to
// https. That makes SvelteKit's origin (used by its CSRF check and by the API's
// own same-origin guard) disagree with the http:// URL the studio is served on.
// Forwarding the real protocol per request keeps both in step.
process.env.PROTOCOL_HEADER = 'x-clipsai-protocol';

// 512 KB (the adapter default) would reject every rendered clip; the publish
// endpoint enforces IndiePost's real 2 GB limit on the declared size.
process.env.BODY_SIZE_LIMIT ??= '3G'; // suffix form used by adapter-node

// Imported after the environment is set: the handler reads both at load time.
const { handler } = await import('./build/handler.js');

const port = Number(process.env.PORT ?? 3000);
const host = process.env.HOST ?? '127.0.0.1';

const server = createServer((request, response) => {
	const forwardedProto = request.headers['x-forwarded-proto'];
	const proto =
		typeof forwardedProto === 'string' && forwardedProto
			? forwardedProto.split(',')[0].trim()
			: request.socket.encrypted
				? 'https'
				: 'http';
	request.headers['x-clipsai-protocol'] = proto;

	for (const [name, value] of Object.entries(isolationHeaders)) {
		response.setHeader(name, value);
	}
	handler(request, response);
});

server.listen(port, host, () => {
	console.log(`ClipsAI Studio listening on http://${host}:${port}`);
});
