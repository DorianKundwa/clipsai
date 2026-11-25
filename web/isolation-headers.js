/**
 * Cross-origin isolation headers, shared by every server the app can run under:
 *
 * - `vite dev` / `vite preview`  -> vite.config.ts plugin (static files bypass
 *   Vite's `server.headers` option, so the plugin sets these on the raw response)
 * - adapter-node routes          -> src/hooks.server.ts
 * - adapter-node static assets   -> server.js (hooks never see them)
 *
 * `Cross-Origin-Embedder-Policy: require-corp` is what actually unlocks
 * SharedArrayBuffer for ffmpeg.wasm's multithreaded core; COOP must match or the
 * browser refuses the isolated context.
 *
 * @type {Readonly<Record<string, string>>}
 */
export const isolationHeaders = {
	'Cross-Origin-Opener-Policy': 'same-origin',
	'Cross-Origin-Embedder-Policy': 'require-corp',
	// Anything the page loads from us (ffmpeg core, wasm, worker) may be
	// embedded by our own origin only.
	'Cross-Origin-Resource-Policy': 'same-origin',
	// Keep the document in its own agent cluster.
	'Origin-Agent-Cluster': '?1'
};
