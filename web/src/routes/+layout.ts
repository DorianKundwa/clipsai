// This is a local, browser-first editor: every route depends on File, Blob,
// Worker and canvas APIs, so there is nothing meaningful to render on the server.
export const ssr = false;
export const prerender = false;
