# Publishing with IndiePost

ClipsAI publishes rendered clips through [IndiePost](https://www.indiepost.app).
The key lives in the backend environment, never in the Studio UI.

```bash
# .env (gitignored)
INDIEPOST_API_KEY=ip_...
INDIEPOST_BASE_URL=https://www.indiepost.app
```

## API flow

Every call sends `Authorization: Bearer ip_…` to
`https://www.indiepost.app/api/v1` (override with `INDIEPOST_BASE_URL`).

| Endpoint | Purpose |
| --- | --- |
| `GET /accounts` | Workspaces, each with `id`, `name`, `isDefault` and its `accounts` (`platform`, `connected`, `username`). |
| `POST /media` | `{filename, mimeType, size}` → `{mediaId, mime, size, upload: {method, url, expiresInSeconds}}`. |
| `PUT <upload.url>` | The clip bytes, with the declared `Content-Type`. The signed URL needs no Bearer header; it expires in 10 minutes. |
| `POST /media/confirm` | `{mediaId}` → `{ok, mediaId, key}`. **Required** before a media id can be posted. |
| `GET /media` | `{items: [{mediaId, filename, mime, size, inUse}]}` — reuse a `mediaId` instead of uploading again. |
| `POST /media/import` | `{driveFileIds: [...]}` → `{items, remaining}` for files already in Google Drive. |
| `DELETE /media/:id` | Remove one stored file (`inUse: true` files are referenced by a post). |
| `POST /posts` | `mediaIds`, `platforms`, `caption`, `when` (`"now"` or an ISO timestamp) and the per-platform blocks below. |
| `GET /posts?from=&to=` | Post groups in a window (`from`/`to` ISO 8601), each with per-platform `status` and `externalPostId`. |
| `GET /posts/:id` | One post group's current status. |
| `DELETE /posts/:id` | Delete a group from every platform. |
| `POST /batches` | `{defaults, cadence: {start, timezone, postsPerDay}, posts: [...]}` plus an `Idempotency-Key` header; returns `batchId`, results and daily usage. |
| `GET /batches/:id` | Batch results with per-post status. |

The publish sequence is **init → PUT → confirm → post**. An upload that is not
confirmed stays unusable, so both clients call `/media/confirm` between the PUT
and the post.

The client in `clipsai/publish/indiepost.py` wraps every endpoint:
`list_accounts`, `list_media`, `init_media`, `confirm_media`,
`import_media(drive_file_ids)`, `delete_media`, `create_post`,
`schedule_batch(defaults, cadence, posts, idempotency_key)`, `get_post`,
`list_posts(from_, to)`, `delete_post`, `get_batch`. `publish_media(...)` runs
the whole sequence and returns the media id, the confirmed storage `media_key`,
the post and its external ids.

## Web studio: publish an export

The SvelteKit app in `web/` publishes rendered clips through the same API, with
the key held server-side:

- `GET /api/indiepost/accounts` returns the default workspace and its linked
  accounts. The browser never sees the key.
- `POST /api/indiepost/publish` takes the clip as the raw request body and the
  publish details as a base64url `x-clipsai-publish` header (plus
  `x-clip-size` / `x-clip-name`). The size is checked before the body is read,
  then the bytes are streamed through: init media → PUT → **confirm** → post.
- `GET /api/indiepost/media` lists stored media, `DELETE /api/indiepost/media/:id`
  removes one. `GET /api/indiepost/posts?from=&to=` lists post groups (default
  window: two weeks either side of now) and `DELETE /api/indiepost/posts/:id`
  deletes a group from every platform.
- `/library` shows those post groups and files, with per-platform statuses and
  delete actions; it is the place to check what actually went out.

On `/exports`, tick the linked-account chips to choose destinations (the choice is
remembered, and shared with `/studio` and the publish dialog), then press **Publish**
on a clip. Only accounts reporting `connected: true` are selectable, YouTube
requires a title, and the
`Idempotency-Key` is derived from the clip id plus the destination set, so
retrying the same publish cannot double-post.

Configuration: the web app reads `INDIEPOST_API_KEY` and `INDIEPOST_BASE_URL`
from the repository `.env` — `env.dir` points at the repository root in dev, and
`npm start` runs with `--env-file-if-exists=../.env`. Restart the server after
changing the key.

`web/server.js` sets two adapter-node variables before loading the handler:
`PROTOCOL_HEADER` (so the request origin matches the `http://` URL the studio is
served on — otherwise SvelteKit's CSRF check rejects every browser `Origin`) and
`BODY_SIZE_LIMIT` (default `3G`, since the adapter's 512 KB default would refuse
any clip; the publish endpoint still enforces the real 2 GB cap). Set either in
`.env` to override them.

### AI metadata (DeepSeek)

The publish dialog can draft the copy instead of writing it by hand:

- `GET /api/ai/metadata` reports whether a DeepSeek key is configured.
- `POST /api/ai/metadata` takes clip facts (`name`, `start`, `end`, `aspect`,
  `look`, `platforms`, optional `brief` / `existingCaption`) and returns
  `{ title, caption, hashtags[] }`.

The model only sees facts the app already knows plus the optional “what happens
in this clip?” note, and is instructed not to invent people, brands or claims.
The result fills the caption and YouTube title; hashtags are appended to the
caption and shown as chips with a **Remove tags** action. A successful post is
recorded on the export row (platforms plus the first post link, when IndiePost
returns one), and the button becomes **Publish again**. Without a key the
button is disabled. Configure `DEEPSEEK_API_KEY` (optionally
`DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`) in the same `.env`.

## Platform rules

| Platform | Requirements | Optional |
| --- | --- | --- |
| YouTube | `youtube.title`, `youtube.format` (`"short"` or `"long"`) | `aiGenerated` |
| TikTok | `tiktok.privacyLevel`: `PUBLIC_TO_EVERYONE`, `MUTUAL_FOLLOW_FRIENDS`, `FOLLOWER_OF_CREATOR`, `SELF_ONLY` | `commercialEnabled`, `commercialYourBrand`, `commercialBrandedContent`, `aiGenerated` |
| Instagram | — | `format` (`"reel"`/`"post"`), `aiGenerated` |
| Facebook | — | `format` (`"reel"`/`"post"`), `aiGenerated` |
| X | **not available via the API** | — |

A paid-partnership TikTok post (`commercialBrandedContent`) cannot use
`SELF_ONLY` privacy. Limits count post groups (IG + TikTok + YouTube = 1), not
destinations: Free 2 GB/hour and 100 posts/day, Pro 5 GB/hour and 500 posts/day.

## Idempotency

Every post ClipsAI creates sends both an `Idempotency-Key` header and an
`idempotencyKey` body field, derived from the job id, the clip index and the
file content. Retrying a failed request therefore returns the existing post
instead of creating a second one; a re-cut clip gets a new key.

## MCP

IndiePost also exposes the same tools over a hosted MCP server. There are two
setup paths.

### Claude / Cursor / ChatGPT — server URL

```
https://www.indiepost.app/api/mcp
```

Send `Authorization: Bearer ip_...` on every request.

Cursor `mcp.json` (or use `.mcp.json.example` in this repo):

```json
{
  "mcpServers": {
    "indiepost": {
      "url": "https://www.indiepost.app/api/mcp",
      "headers": { "Authorization": "Bearer ip_YOUR_KEY" }
    }
  }
}
```

### Claude.ai custom connector

- URL: `https://www.indiepost.app/api/mcp` (use `www`, not the apex redirect)
- Authentication: **No sign-in** (not OAuth)
- Request headers: `authorization` = `Bearer ip_YOUR_KEY` — the word `Bearer`
  and a space are required

### Tools

`list_accounts`, `list_media`, `init_media_upload`, `delete_media`,
`import_media`, `create_post`, `schedule_batch`, `get_post`, `delete_post`,
`get_batch`.

The MCP server is hosted by IndiePost. Nothing is installed or run locally, and
`clipsai` does not depend on the `mcp` SDK.
