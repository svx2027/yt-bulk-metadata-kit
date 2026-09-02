# Run guide: snapshot through final verification

Total time for a playlist of a dozen or so videos: roughly 25-45 minutes, most
of it automated waiting (comment pacing, API calls). Assumes `auth_setup.py`
has already produced a `token.json` and `config.json` is filled in — see
[`OAUTH_SETUP.md`](OAUTH_SETUP.md) and [`CONFIG.md`](CONFIG.md) if not.

Example output below uses a fictional playlist of 12 videos and illustrative
titles; your actual output will show your real playlist and video titles.

---

## Step 1: snapshot current state

Backs up everything before touching anything.

```
python3 snapshot.py
```

Expected output:
```
Reading playlist: example playlist: season 2 live sessions
Playlist ID: PLxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

Found 12 videos in playlist.
Fetching full metadata for each video...
  [1/12] Live session 12: intro to the topic
  [2/12] Live session 11: continued
  ...
  [12/12] Live session 1: season opener

Snapshot complete. Saved to: snapshot_2026-04-23_19-45-12.csv
Rows written: 12 of 12 videos

KEEP THIS FILE SAFE. It is the only way to revert description changes.
```

Check: `ls snapshot_*.csv` shows at least one file.

## Step 2: dry run

Preview the update with no changes made.

```
python3 update_videos.py --dry-run
```

Checklist on the output:
- [ ] Every video in the playlist is listed
- [ ] Every new title ends with your configured suffix
- [ ] No "VALIDATION FAILED" lines
- [ ] No "ERROR" lines
- [ ] All new title lengths are under 100 chars

A "VALIDATION FAILED: title too long" line means that specific video's title
plus the suffix exceeds YouTube's limit — either shorten the suffix or accept
that video will be skipped.

## Step 3: update one video as a test

```
python3 update_videos.py --limit 1
```

Type `yes` when prompted (this is a real write). Success criterion:
`Updated: 1, Errors: 0`.

## Step 4: verify the test video

```
python3 verify.py --limit 1
```

Confirms via a fresh API read (not the update script's own assumption) that
the title, description, tags, and language settings landed as expected. Also
open the printed public URL in a browser to eyeball it directly.

If anything looks wrong: `python3 revert.py --limit 1` restores it before you
go further.

## Step 5: update the rest

```
python3 update_videos.py
```

Type `yes`. The script auto-skips the video already done in Step 3 (reads
`update_log.csv`). If some videos error out, just re-run the same command —
idempotency means only the failed ones are retried.

## Step 6: post comments

Dry run first:
```
python3 post_comments.py --dry-run
```

Then for real:
```
python3 post_comments.py
```

Type `yes`. This takes a few minutes for a dozen videos — 8-15 seconds of
deliberate pacing between each post to avoid tripping YouTube's spam filter.
If some fail with `processingFailure`, wait about 10 minutes and re-run the
same command; idempotency retries only what didn't succeed. `commentsDisabled`
failures are normal for some videos (e.g. certain live streams) and are
skipped automatically, not retried.

## Step 7: final verification

```
python3 verify.py
```

Prints (and saves) a report of every video's current live state — useful to
send to the channel owner as proof of what changed, without needing to give
them Studio access to check it themselves. Two or three of the public
`youtube.com/watch?v=...` links from the report are usually enough for a
visual spot-check on their end.

If the channel owner asks about pinning the new comment: the API cannot pin
comments (a YouTube Data API limitation, not something this kit can work
around). Pinning is a 5-second manual click per video: comment's 3-dot menu →
Pin, in YouTube Studio.

## Afterward

**Keep:** the snapshot CSV (30+ days, it's your only revert path),
`update_log.csv` and `comments_log.csv` (audit trail), the verify report.

**Never share or commit:** `client_secret.json`, `token.json`.

**To run again on a different playlist:** change `playlist_id` (and
`playlist_name`) in `config.json`, repeat from Step 1. The token stays valid
for 7 days from authorization regardless of how many playlists you run.
