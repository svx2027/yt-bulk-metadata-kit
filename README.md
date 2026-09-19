# yt-bulk-metadata-kit

[![tests](https://github.com/svx2027/yt-bulk-metadata-kit/actions/workflows/tests.yml/badge.svg)](https://github.com/svx2027/yt-bulk-metadata-kit/actions/workflows/tests.yml)

Bulk-update the title, description, and tags across every video in a YouTube
playlist, using the official YouTube Data API v3 through OAuth (not a headless
browser, not a channel login). Also snapshots current metadata for a one-command
revert, and can post the same top-level comment across every video in the
playlist.

Built for a specific real use case: a channel owner needed a batch of old live
streams retitled, re-tagged, and cross-promoted with a new comment ahead of a
new content season, and needed to be able to see the change confirmed and, if
necessary, undone. Every script here is config-driven (no channel or client
identity baked in) and safe to re-run.

## What it does

- `auth_setup.py` — one-time OAuth flow with the channel owner. You never see
  or need their password; they authorize a token, you paste the redirect URL
  back, done.
- `snapshot.py` — backs up every video's current title, description, tags,
  category, and language settings to a timestamped CSV before you touch
  anything. This is the file that makes `revert.py` possible.
- `update_videos.py` — for every video in the configured playlist: appends a
  title suffix, replaces the description and tags from `config.json`, and
  preserves everything the YouTube API would otherwise silently wipe
  (`categoryId`, `defaultLanguage`, `defaultAudioLanguage`). Validates length
  limits before sending. Supports `--dry-run`, `--limit N`, `--only VIDEO_ID`.
- `post_comments.py` — posts one top-level comment on every video in the
  playlist, paced 8-15 seconds apart to avoid YouTube's spam filter. The API
  cannot pin comments; pinning stays a manual, 5-second click per video in
  YouTube Studio.
- `verify.py` — re-fetches every video's live state from the API and prints
  (and optionally saves) a human-readable report, so you can prove the update
  worked without needing Studio access to the channel yourself.
- `revert.py` — restores metadata from the most recent snapshot CSV. Does not
  un-post comments (YouTube's API has no bulk-delete for those); that stays
  manual.

## Why this exists instead of doing it by hand in Studio

At more than a handful of videos, doing this by hand in YouTube Studio is slow
and has no audit trail and no easy way to prove to a channel owner (who may not
be the one running the script, and may not want to hand out Studio access)
exactly what changed. This kit makes the whole operation: previewable
(`--dry-run`), resumable (every script is idempotent — it reads its own log and
skips what already succeeded, so a crash or a rate limit mid-run just means
re-running the same command), reversible (`snapshot.py` before, `revert.py` if
needed), and provable (`verify.py`'s report, generated from a live API read, not
from what the script thinks it did).

## Setup

1. `pip install -r requirements.txt`
2. Create a Google Cloud project, enable the YouTube Data API v3, and create an
   OAuth Client ID of type **Desktop app**. Download it as `client_secret.json`
   in this folder. Full walkthrough, including why OAuth (not a password) is
   the only acceptable way to do this: [`OAUTH_SETUP.md`](OAUTH_SETUP.md).
3. Copy `config.example.json` to `config.json` and fill in your playlist ID and
   the title/description/tags/comment you want applied. Field-by-field
   explanation: [`CONFIG.md`](CONFIG.md).
4. Run `python3 auth_setup.py` and follow the prompts.
5. Follow [`RUN_GUIDE.md`](RUN_GUIDE.md) for the full snapshot -> dry-run ->
   test-one -> verify -> update-rest -> comment -> verify-again sequence.

If something goes wrong at any step, [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)
is organized by phase and covers the errors this kit has actually hit in
production, not a generic FAQ. [`FAILURE_MODES.md`](FAILURE_MODES.md) is the
other direction — read it once before a real run: the ways this can go wrong
silently (a wrong-channel auth, a duplicate comment, an un-revertable video)
that you won't see as an error message until after they've already happened.

## Tests

```bash
pip install -r requirements.txt
python3 -m unittest discover -s tests -v
```

13 tests covering `_helpers.py`'s error classification and CSV log helpers —
the logic every script leans on for its retry/backoff decisions and its
idempotency (skipping video IDs a previous run already completed). No
network calls and no OAuth token needed, so `.github/workflows/tests.yml`
runs the same suite on every push and pull request with no secrets
configured. **Not covered:** the actual YouTube Data API calls
(`snapshot.py`, `update_videos.py`, `post_comments.py`, `verify.py`,
`revert.py`'s live paths) — those need a real OAuth token against a real
channel, which is exactly what "No sample run is included" below is about.

## Honest scope

- **Testing-mode OAuth tokens expire after 7 days.** Fine for a single batch
  run; re-run `auth_setup.py` if you come back later. Submitting the Cloud
  project for verification removes this limit but is out of scope here.
- **The API cannot pin comments.** There is no way around this from
  `post_comments.py` or any API call; it's a deliberate YouTube Data API
  limitation. Pinning stays a manual click per video.
- **`revert.py` restores metadata, not comments.** A posted comment can only be
  removed manually (or through YouTube Studio's bulk moderation tools).
- **Every write replaces the full snippet.** The YouTube API's
  `videos.update` call takes the entire `snippet` object, not a per-field
  patch — send only title/description/tags and the API silently wipes
  `categoryId`, `defaultLanguage`, and `defaultAudioLanguage`. `snapshot.py`
  and `update_videos.py` exist specifically to read those fields first and
  carry them forward; skipping the snapshot step means losing them.
- **No sample run is included.** This kit talks to a real channel's videos
  through OAuth; there is no keyless, no-side-effects way to demonstrate it
  against a channel that isn't yours. The scripts and their idempotency /
  retry / validation logic are the artifact to read.

## License

MIT, see [LICENSE](LICENSE).
