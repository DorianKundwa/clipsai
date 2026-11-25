#!/usr/bin/env node
/**
 * Copies the multi-threaded ffmpeg.wasm core next to the app so it is served
 * same-origin from /ffmpeg/.
 *
 * Why copy instead of importing the files with `?url`: the core-mt build
 * resolves its pthread worker relative to the *script* URL
 * (`ffmpeg-core.worker.js`). Vite hashes asset filenames, so a bundled copy
 * breaks that lookup. Stable, unhashed filenames keep the core self-consistent,
 * and they can be cached by the browser independently of app builds.
 */
import { copyFile, mkdir, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = path.join(root, 'node_modules', '@ffmpeg', 'core-mt', 'dist', 'esm');
const dest = path.join(root, 'static', 'ffmpeg');

const FILES = ['ffmpeg-core.js', 'ffmpeg-core.wasm', 'ffmpeg-core.worker.js'];

try {
  await stat(src);
} catch {
  // Dependencies are not installed yet (e.g. a bare `npm install` in CI that
  // skips scripts). Nothing to copy, and nothing to fail on.
  console.log('[ffmpeg] core-mt not installed yet, skipping core sync');
  process.exit(0);
}

await mkdir(dest, { recursive: true });

for (const file of FILES) {
  const from = path.join(src, file);
  const to = path.join(dest, file);
  try {
    const info = await stat(from);
    const existing = await stat(to).catch(() => null);
    if (existing && existing.size === info.size && existing.mtimeMs >= info.mtimeMs) continue;
    await copyFile(from, to);
    console.log(`[ffmpeg] ${file} -> static/ffmpeg/${file}`);
  } catch (error) {
    console.warn(`[ffmpeg] could not copy ${file}: ${error.message}`);
  }
}
