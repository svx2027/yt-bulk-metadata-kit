# Troubleshooting

Organized by phase. These are the actual failure modes this kit has hit in
production, not a generic FAQ.

---

## Environment / install

**`error: externally-managed-environment` during `pip install`**
Python 3.11+ blocks system-wide installs by default.
```
pip3 install --break-system-packages -r requirements.txt
```

**`pip3: command not found`**
```
python3 -m pip install -r requirements.txt
```

**`Could not install packages due to an OSError: [Errno 13] Permission denied`**
```
pip3 install --user -r requirements.txt
```

**`ModuleNotFoundError: No module named 'googleapiclient'` when running a script**
The install landed in a different Python than the one running the script.
Re-run the install with the exact `python3`/`pip3` you use to run the scripts,
or use a virtualenv to avoid ambiguity.

---

## OAuth authorization (`auth_setup.py`)

**Channel owner sees "Error 403: access_denied"**
They signed in with the wrong Google account. Have them retry in an
incognito/private window and pick the account that actually owns the channel.

**"Error 400: redirect_uri_mismatch"**
The OAuth client in Google Cloud Console was not created as type "Desktop
app." Create a new one with that type, download it as `client_secret.json`,
replace the existing file, re-run.

**Stuck at "Google hasn't verified this app"**
Expected for an app still in Testing mode. Click **Advanced**, then the small
"Go to [app name] (unsafe)" link. Not a security issue — it's Google's UI for
apps that haven't gone through the (optional, paid at scale) verification
review.

**Error page after clicking Allow, URL starts with `http://localhost:8080/?code=...`**
Expected. Copy the full URL from the address bar and paste it into the waiting
prompt. Don't close the error page first.

**`invalid_grant` after pasting the URL**
The authorization code is single-use and short-lived (about 60 seconds).
Re-run `auth_setup.py`, get a fresh URL, complete the exchange quickly.

**"The state parameter doesn't match"**
Usually caused by running `auth_setup.py` in two terminals at once. Close all
of them, open one fresh, re-run.

**Channel name in the sanity check doesn't match expectations**
The authorizing account isn't the one that owns the target channel.
```
rm token.json
python3 auth_setup.py
```
and confirm with the channel owner which Google account owns the channel.

**`token.json` exists but scripts fail with an auth error**
Expired (7-day Testing-mode limit) or revoked.
```
rm token.json
python3 auth_setup.py
```

---

## Snapshot

**"ERROR: token.json not found"**
Run `auth_setup.py` first.

**"WARNING: N video(s) were not accessible"**
Some playlist entries are private, deleted, or belong to another channel.
They're skipped automatically everywhere. Run `verify.py` to see exactly
which ones.

---

## Update videos

**"VALIDATION FAILED: title too long"**
That video's title plus the configured suffix exceeds YouTube's 100-character
limit. Either shorten the suffix, shorten that video's title manually first,
or accept that video stays un-updated.

**"Transient error (503), retry in 2.0s..."**
Normal — the API had a hiccup, the built-in retry (exponential backoff, up to
3 attempts) is handling it. No action needed.

**Script finishes with some errors**
Re-run the same command. Idempotency means already-updated videos are
skipped and only the failed ones are retried.

**"auth error" and the script exits**
Token expired or was revoked mid-run. `python3 auth_setup.py`, then re-run the
same update command — it resumes from where it stopped.

**Nothing visible changes on YouTube after a successful update**
YouTube's CDN/cache can lag 30-60 seconds. Hard-refresh, or just trust
`verify.py`'s API read over eyeballing the page.

**`update_log.csv` shows `status=error, reason=forbidden`**
The authenticated account doesn't own that video — shouldn't happen with
correct auth unless the playlist includes a video from another channel.
Skip it, continue with the rest.

---

## Comments

**"Comments disabled on this video, skipping"**
Normal for some videos (frequently live streams, or made-for-kids content).
Logged as skipped, not an error.

**Multiple `processingFailure` errors**
YouTube's spam filter tripped from posting many similar comments quickly.
Wait about 10 minutes, re-run `post_comments.py` — idempotency retries only
what failed. If it's still failing after that, wait longer, or vary the
comment text slightly to avoid pattern detection.

**A comment posted successfully (per the log) but is missing from the video**
The spam filter can silently remove a comment after the API already reported
success. `comments_log.csv` will still show `posted`. Waiting and checking
again is usually enough; if it's genuinely gone, `--force` re-posts it (this
creates a duplicate if the original later reappears, so use with care).

**Comments land in "Held for review" instead of appearing publicly**
The channel has comment moderation turned on. The channel owner needs to
approve them in YouTube Studio → Comments → Held for review.

**Why does this take several minutes for a dozen videos?**
Intentional 8-15 second delay between posts, specifically to avoid the spam
filter. Not a bug.

---

## Verification

**`verify.py` output doesn't match what you expected**
Cross-check `update_log.csv` — the video may genuinely not have been updated
yet, or you may be looking at the wrong playlist.

---

## Revert

**"No snapshot_*.csv files found"**
`snapshot.py` was never run before the update. Without a snapshot there's no
automated revert path; recovery would need to be done manually in Studio from
memory or from `update_log.csv`'s `old_title` column (titles only — the
original description and tags aren't captured anywhere except the snapshot).

**Revert itself has errors**
Same idempotency applies — re-run, only the failed reverts retry.

**Revert doesn't remove posted comments**
By design — the YouTube API has no bulk-delete for comments. Remove them
manually in Studio if needed.

---

## General

**The process was interrupted mid-run (sleep, network drop, Ctrl+C)**
Every script is idempotent by design: it reads its own log at startup and
skips whatever already succeeded. Just re-run the same command.

**Ran the wrong script by accident**
- `update_videos.py`: run `verify.py --limit 5` to check, `revert.py` if
  needed.
- `post_comments.py`: check `comments_log.csv`, delete unwanted comments
  manually in Studio.
- Anything else (`snapshot.py`, `verify.py`): read-only, nothing to undo.
