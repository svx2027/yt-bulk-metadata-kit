# Design notes: why the scripts are built this way

Each of these came from a real failure mode considered (or hit) while building
this kit, not a hypothetical checklist.

**Idempotency everywhere.** If `update_videos.py` dies on video 7 of 20,
re-running it naively would re-update videos 1-6 — wasted API quota at best,
duplicate side effects at worst. Every script that writes (`update_videos.py`,
`post_comments.py`, `revert.py`) reads its own CSV log at startup, builds the
set of already-successful video IDs, and skips them. Any script is safe to
re-run at any point, which also means a mid-run crash costs nothing but the
time already spent.

**Retry with backoff, but only where it's safe.** YouTube's API returns 429,
500, 502, 503, and 504 on transient load. `_helpers.py` retries those with
exponential backoff (2s, 4s, 8s + jitter, up to 3 attempts) — but auth errors
never retry (they won't succeed the second time and should surface
immediately), and per-video errors like `commentsDisabled` or `videoNotFound`
never retry either (retrying won't fix a video that structurally can't accept
the write; it just wastes time).

**Comment pacing is deliberate, not a default.** Posting many identical
comments back-to-back reliably trips YouTube's spam filter — comments either
fail outright with `processingFailure`, or worse, succeed at the API layer and
get silently removed minutes later. The 8-15 second randomized delay between
posts in `post_comments.py` is sized from observed behavior, not a guess.

**The full-snippet-replace trap.** `videos().update()` takes the *entire*
`snippet` object — send only `title`/`description`/`tags` and the API happily
wipes `categoryId`, `defaultLanguage`, and `defaultAudioLanguage` with no
warning. `snapshot.py` captures those fields before any write, and
`update_videos.py` reads them fresh and carries them forward on every update.
Skipping the snapshot step means those fields are unrecoverable if a run wipes
them.

**Validate before sending, don't rely on the API to reject cleanly.** Title
length, non-empty description, and total tag-character limits are checked
client-side before the write. Some of the API's own error responses for these
cases are generic enough to be unhelpful for figuring out *which* field
failed; catching it before the request avoids that ambiguity entirely, and
means a failing video is clearly logged with a reason rather than a raw HTTP
error.

**A read-only verification step, independent of what the update script
believes it did.** `verify.py` doesn't consult any log file — it re-fetches
current state directly from the API. This matters when the person running the
scripts doesn't have (and shouldn't need) Studio access to the target channel:
the verify report is the proof, generated from the same source of truth
YouTube itself uses, not from the update script's own bookkeeping.

**Auth failures fail loudly and immediately, not as a generic error N videos
in.** `classify_error()` distinguishes an expired/revoked token from a
transient API hiccup from a per-video issue. Only the auth case exits the
whole run with an explicit "re-run `auth_setup.py`" message — the whole point
being that after re-authorizing, every other script picks up exactly where it
left off (idempotency again) instead of needing anything replayed by hand.

**Revert intentionally does not touch comments.** The YouTube API has no
bulk-delete for comments, so a "full" revert of a comment-posting run isn't
technically possible from this kit — this is disclosed rather than
papered over, in [`README.md`](README.md)'s honest-scope section and in
`revert.py`'s own docstring.
