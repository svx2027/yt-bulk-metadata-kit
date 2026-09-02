# Configuration reference

`config.json` (copy from `config.example.json`) controls exactly what the
scripts will write. It is gitignored — never commit your real one, since it
often contains a real playlist ID and channel-specific copy. Review it before
running anything against a real channel.

## Fields

**`playlist_id`**
The playlist to operate on. `snapshot.py`, `update_videos.py`,
`post_comments.py`, and `verify.py` all read every video *in this one
playlist* directly from the API. (`revert.py` is the exception: it restores
from a snapshot CSV file, not from `playlist_id`, so it works even if the
video has since been removed from the playlist.) To operate on a different
playlist, point this at it — there's no multi-playlist mode; run the full
sequence again per playlist.

**`playlist_name`**
Human-readable label, printed in script output. Cosmetic only, no functional
effect.

**`title_suffix`**
Appended to every existing video title (e.g. `" | Season 2"` — note the
leading space is intentional if you want a space before the suffix).
`update_videos.py` validates the resulting title stays under YouTube's 100
character limit and skips (does not truncate) any video where it wouldn't.

**`description_template`**
**Replaces** every video's existing description outright. Newlines are
written as `\n` in the JSON. `snapshot.py` preserves the original text before
this runs, so it's recoverable via `revert.py`.

**`tags`**
A JSON array of strings. **Replaces** the existing tag list. YouTube caps the
total character count across all tags combined at 500; `update_videos.py`
validates this and skips (does not truncate) any video that would exceed it.

**`comment_text`**
Posted as a new top-level comment on every video by `post_comments.py`. Does
not touch or replace any existing comments.

## What a full run actually does, per video

**`update_videos.py`** (metadata):
1. Fetch current title, description, tags, category, and language settings.
2. (Separately, via `snapshot.py`, ideally run first) write all of the above
   to a CSV — this is the revert insurance.
3. Build the new title = old title + `title_suffix`.
4. Validate: title under 100 chars, description non-empty, tags under 500
   total chars.
5. Push the update: new title, new description, new tags, with `categoryId`,
   `defaultLanguage`, and `defaultAudioLanguage` carried forward unchanged.
6. Log the result to `update_log.csv`.

**`post_comments.py`** (comments), run separately:
1. Post `comment_text` as a new top-level comment.
2. Wait 8-15 seconds (spam-filter mitigation — see
   [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)).
3. Log the result to `comments_log.csv`.

## Destructiveness, plainly

- **Descriptions are wiped and replaced.** The original text is lost from
  YouTube but captured in the snapshot CSV, so it can be restored.
- **Titles are appended to, not replaced.** Reverting strips the suffix back
  off (restores the exact original from the snapshot).
- **Posted comments stay posted** until manually deleted in YouTube Studio.
  `revert.py` does not touch comments.

## Editing config.json

Standard JSON rules apply: strings in double quotes, escape internal quotes
with `\"`, escape newlines as `\n`, no trailing commas, and don't rename the
keys (the scripts read them by exact name). After editing, sanity-check it
parses:

```
python3 -c "import json; json.load(open('config.json')); print('valid')"
```
