# Failure-mode playbook

[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) is indexed by error message: you saw
something, you look it up. This doc is the other direction — read it once
*before* a real run against a channel you can't easily undo. Each item below
was found by reading the actual retry/idempotency/logging code in
[`_helpers.py`](_helpers.py) and the five scripts, not by guessing at what
might go wrong. Ranked by how bad the outcome is if you don't know about it
going in, worst first.

---

## 1. Wrong-channel authorization is not caught by default

`auth_setup.py` has a built-in sanity check: after the OAuth exchange, it
fetches the authorized channel's name and can compare it against
`EXPECTED_CHANNEL_NAME_CONTAINS`, a constant at the top of the file. Out of
the box that constant is `""`. With it empty, the check
(`if not EXPECTED_CHANNEL_NAME_CONTAINS or ... in channel_title`) is always
true, so the script always prints "All good. You are authorized to manage
this channel" — regardless of which channel actually authorized.

**Why it matters:** if the channel owner signs in with the wrong Google
account (a personal account instead of the one that owns the channel), you get
back a completely valid, working token. Every later script runs successfully
against *that* account's videos with zero warning that it's the wrong channel.

**What to do:** before running against a channel you don't personally own or
control, open `auth_setup.py` and set `EXPECTED_CHANNEL_NAME_CONTAINS` to a
substring of the real channel's name first. It's a one-line edit; it is not
exposed in `config.json` today.

---

## 2. A corrupted log makes a re-run repeat live writes — not just for comments

`read_completed_ids_from_log()` in `_helpers.py` has a deliberate fallback: if
the log CSV can't be parsed partway through, it returns whatever rows it
managed to read before the failure — an empty set if the corruption is right
at the start of the file, a partial set otherwise. Either way, some or all of
the previously-successful video IDs stop being recognized as "already done."

That fallback is not equally safe across the two write scripts it protects.

- **`post_comments.py`**: `commentThreads.insert` always creates a brand-new
  comment — there's no dedupe at the YouTube API layer, only the log-based
  kind this script builds. A corrupted or lost `comments_log.csv` means every
  video the log no longer remembers gets a second, live, public duplicate
  comment.
- **`update_videos.py`**: description and tags are static overwrites from
  `config.json`, so re-sending them to an already-updated video is harmless.
  The **title is not**. `build_new_snippet()` builds the new title from
  `old_snippet["title"]` — the video's *current live title*, fetched fresh
  every run, not the original. If a corrupted `update_log.csv` causes an
  already-suffixed video to be reprocessed, the configured suffix gets
  appended a **second time** — and a third, on the next bad re-run — with the
  title getting progressively longer and more wrong each repeat.

**What to do:** after any unclean stop (Ctrl+C, crash, killed process,
machine losing power) during or after an `update_videos.py` or
`post_comments.py` run, open the corresponding log CSV and confirm it's
intact and parses as normal CSV before re-running. If it looks damaged,
spot-check a few videos directly (current live title, and whether a comment
already exists) before re-running broadly, or restrict the re-run with
`--only VIDEO_ID` to the specific videos you've confirmed still need it.

---

## 3. Daily API quota exhaustion doesn't stop the run — it fails every remaining video, one at a time

`classify_error()` only recognizes three special buckets: retryable
(`429, 500, 502, 503, 504`), auth (`invalid_grant`, `invalid_token`,
`unauthorized`, `authError`, or HTTP 401), and per-video (`commentsDisabled`,
`forbidden`, `videoNotFound`, `processingFailure`, `commentRejected`,
`invalidVideoMetadata`). A quota-exhaustion error from Google (HTTP 403,
reason `quotaExceeded` or `dailyLimitExceeded`) matches none of those, so it
falls through to `"permanent"` — the same bucket as "this one video is
structurally broken." `update_videos.py` and `post_comments.py` both treat a
permanent error as "log it, move to the next video," not "stop the whole
run." If quota runs out at video 40 of 200, you get 160 back-to-back
`ERROR (permanent, status 403, reason 'quotaExceeded')` lines instead of one
clear stop.

**Why it's plausible, not hypothetical:** the writes this kit makes —
`videos.update` and `commentThreads.insert` — are each 50 units against the
YouTube Data API's default per-project quota of 10,000 units/day (published
by Google). A single playlist of a dozen videos costs a few hundred units.
A playlist in the hundreds, run for both metadata and comments the same day,
or a project already spent down by other work, can genuinely hit the ceiling.

**How you'll notice:** the run's final summary shows a high `Errors` count,
and `update_log.csv` / `comments_log.csv` show a long run of the same
`reason`.

**What to do:** stop, wait for the daily quota reset (midnight Pacific Time
for the default per-project quota), then re-run the exact same command —
idempotency skips everything already marked successful and retries only what
actually failed. For a playlist large enough to risk this, use `--limit` to
spread the run across more than one day rather than finding out mid-run.

---

## 4. A video added to the playlist after `snapshot.py` runs has no revert path

`revert.py` restores only the video IDs present as rows in the snapshot CSV.
`snapshot.py`, `update_videos.py`, and `post_comments.py` each independently
re-fetch the *live* playlist at the moment they run — they don't share a
frozen view. If a video is added to the playlist in the gap between running
`snapshot.py` and running `update_videos.py`, that video gets updated (it's
in the live playlist `update_videos.py` reads) but has no row in the
snapshot CSV `revert.py` reads from. `revert.py` won't error on it — it will
simply never mention it, because it never sees a reason to.

**What to do:** run `snapshot.py` again immediately before `update_videos.py`
if there's any real chance the playlist changed in between — don't snapshot
on Monday and update on Friday. Compare the "Found N videos" line each script
prints; a mismatch is your signal something changed.

---

## 5. Interrupted or partial runs leave the channel in a mixed, but recoverable, state

If the process dies between `update_videos.py` finishing and
`post_comments.py` starting (or partway through either one), the channel is
left with some videos updated and others not, or some commented and others
not. This isn't a bug to fix — every write script is independently idempotent
by design (see [`DESIGN_NOTES.md`](DESIGN_NOTES.md)) specifically so this is
recoverable: re-run `update_videos.py` to completion first, confirm with
`verify.py`, then run `post_comments.py`. Never run the two out of order or
interleave manual edits with an in-progress run — the scripts only account
for their own state, not for changes made outside them mid-run.

---

## 6. A dropped network connection or a sleeping machine mid-run

A long run (a large playlist, or the paced 8-15s-per-post comment phase) is
exposed to whatever the machine running it does for an hour or so — most
commonly the OS suspending the network, or the process simply losing its
connection. The retry logic in `_helpers.py` absorbs a brief blip; it does
not survive an extended sleep or a dead connection, and the script will
either hang or exit with a connection error. This is not data loss — the same
idempotency covering item 5 means the fix is just "keep the machine awake for
the duration, then re-run the same command if it does stop partway."

---

## 7. A comment can report success and still not be there

Covered in depth in [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md#comments), but
worth flagging here because it's the one failure mode that looks like a
false *success* rather than an obvious error: YouTube's spam filter can
accept a comment at the API layer (`comments_log.csv` shows `posted`) and
silently remove it minutes later. `verify.py` doesn't check comments, only
video metadata, so this needs a manual spot-check on the actual video pages
if you want to be sure a comment landed and stayed.
