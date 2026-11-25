import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { defineConfig, type Plugin, type PreviewServer, type ViteDevServer } from 'vite';
import { isolationHeaders } from './isolation-headers.js';

/**
 * `server.headers` only covers responses Vite itself generates. Files in
 * `static/` are answered by Vite's static middleware, which writes its own
 * response — so the ffmpeg core worker arrived without CORP and Chrome blocked
 * it under COEP. Setting the headers on the prepared response, before the
 * static handler can answer, keeps dev and preview identical to production.
 */
function crossOriginIsolation(): Plugin {
	const install = (server: ViteDevServer | PreviewServer) => {
		const apply = (response: import('node:http').ServerResponse) => {
			for (const [name, value] of Object.entries(isolationHeaders)) {
				response.setHeader(name, value);
			}
		};

		server.middlewares.use((_request, response, next) => {
			apply(response);
			next();
		});

		// `middlewares.use` appends, but the static handler answers /ffmpeg/*
		// before reaching it. A prepended request listener runs first.
		server.httpServer?.prependListener('request', (_request, response) => apply(response));
	};

	return {
		name: 'clipsai:cross-origin-isolation',
		configureServer: (server) => install(server),
		configurePreviewServer: (server) => install(server)
	};
}

export default defineConfig({
	plugins: [
				sveltekit({
			// adapter-node keeps the real Node server in the build output.
			adapter: adapter(),
			preprocess: vitePreprocess(),
			// The web app and the Python backend share the repository .env, so the
			// IndiePost key is configured in one place.
			env: { dir: '..' }
		}),
		crossOriginIsolation()
	],

	server: {
		host: '127.0.0.1',
		port: 5173,
		strictPort: true,
		headers: isolationHeaders
	},

	preview: {
		headers: isolationHeaders
	},

	// FFmpeg's worker bootstrap is shipped pre-bundled; letting Vite re-bundle
	// it breaks its internal `importScripts`/worker URL resolution.
	optimizeDeps: {
		exclude: ['@ffmpeg/ffmpeg', '@ffmpeg/util']
	},

	worker: {
		format: 'es'
	},

	build: {
		target: 'esnext',
		// Never inline assets: the ffmpeg core and wasm must stay as real,
		// separately cached requests.
		assetsInlineLimit: 0
	}
});
