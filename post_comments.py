"""
post_comments.py

Posts a top-level comment on each video in the configured playlist.

Key features:
- Idempotent: reads comments_log.csv, skips videos already commented
- 8-15 second randomized delay between posts (spam filter mitigation)
- Retry on transient errors
- Handles commentsDisabled cleanly (skips, continues)
- Detects token expiry, exits with clear re-auth message

Note: YouTube API v3 cannot pin comments. This script only posts.
Pinning is manual in YouTube Studio (5 seconds per comment).

Flags:
  --dry-run       Preview, don't post
  --limit N       Only process first N videos
  --only VID      Only post on this video
  --force         Re-post even if already in log (will create duplicates!)
"""

import argparse
import random
import sys
import time
from datetime import datetime


from _helpers import (
    load_config,
    load_youtube_client,
    get_video_ids_in_playlist,
    with_retry,
    classify_error,
    handle_auth_error_and_exit,
    read_completed_ids_from_log,
    append_log,
)

LOG_FILE = "comments_log.csv"
LOG_FIELDS = [
    "timestamp", "video_id", "comment_id", "comment_preview",
    "status", "reason", "error_message", "dry_run",
]

SUCCESS_STATUSES = {"posted"}
COMMENT_MAX = 10000

# Randomized delays (seconds) between successful posts to avoid spam filter
DELAY_MIN = 8
DELAY_MAX = 15


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--only", type=str, default=None)
    p.add_argument("--force", action="store_true")
    return p.parse_args()


def log(video_id, comment_id, preview, status, reason="", error_message="", dry_run=False):
    append_log(LOG_FILE, {
        "timestamp": datetime.now().isoformat(),
        "video_id": video_id,
        "comment_id": comment_id,
        "comment_preview": preview[:80],
        "status": status,
        "reason": reason,
        "error_message": error_message[:500] if error_message else "",
        "dry_run": str(dry_run),
    }, LOG_FIELDS)


def main():
    args = parse_args()
    config = load_config()
    comment_text = config["comment_text"]

    if not comment_text.strip():
        print("ERROR: comment_text in config.json is empty.")
        sys.exit(1)
    if len(comment_text) > COMMENT_MAX:
        print(f"ERROR: comment is {len(comment_text)} chars, max {COMMENT_MAX}.")
        sys.exit(1)

    print()
    print("Comment text to post:")
    print("-" * 70)
    print(comment_text)
    print("-" * 70)
    print()

    if args.dry_run:
        print("DRY RUN MODE, no comments will be posted")
    else:
        print("LIVE MODE, comments WILL be posted on YouTube")
        print(f"Pacing: {DELAY_MIN}-{DELAY_MAX}s randomized delay between posts")
        confirm = input("Proceed? Type 'yes' to confirm: ").strip().lower()
        if confirm != "yes":
            print("Cancelled.")
            sys.exit(0)

    youtube = load_youtube_client()

    print()
    print(f"Reading playlist: {config['playlist_name']}")
    items = get_video_ids_in_playlist(youtube, config["playlist_id"])
    print(f"Found {len(items)} videos.")

    # Idempotency
    already_done = set()
    if not args.force and not args.dry_run:
        already_done = read_completed_ids_from_log(LOG_FILE, SUCCESS_STATUSES)
        if already_done:
            print(f"Found {len(already_done)} videos already commented on, will skip.")

    if args.only:
        items = [it for it in items if it["video_id"] == args.only]
        if not items:
            print(f"ERROR: Video {args.only} not in this playlist.")
            sys.exit(1)
    else:
        items = [it for it in items if it["video_id"] not in already_done]
        if args.limit:
            items = items[:args.limit]

    if not items:
        print("Nothing to process. All videos already have comments per the log.")
        print("Use --force if you want to post again (will create duplicates).")
        sys.exit(0)

    print(f"Will post on {len(items)} videos.")
    estimated = len(items) * ((DELAY_MIN + DELAY_MAX) / 2)
    print(f"Estimated time: ~{int(estimated)} seconds ({estimated/60:.1f} min)")
    print()

    posted = 0
    errors = 0
    skipped = 0

    for i, item in enumerate(items, 1):
        vid = item["video_id"]
        title = item["title"][:60]
        print(f"[{i}/{len(items)}] {title}")

        if args.dry_run:
            print(f"  [DRY RUN] would post comment")
            log(vid, "", comment_text, "dry_run_ok", "", "", True)
            continue

        def do_insert():
            return youtube.commentThreads().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": vid,
                        "topLevelComment": {
                            "snippet": {"textOriginal": comment_text},
                        },
                    },
                },
            ).execute()

        result, err = with_retry(do_insert, max_attempts=3, base_delay=2.0)

        if err is not None:
            category, status, reason = classify_error(err)
            if category == "auth":
                log(vid, "", comment_text, "error", "auth", str(err), False)
                handle_auth_error_and_exit(err)

            if reason == "commentsDisabled":
                print(f"  Comments disabled on this video, skipping")
                log(vid, "", comment_text, "skipped", "commentsDisabled", "", False)
                skipped += 1
                continue

            if reason == "processingFailure":
                print(f"  Spam filter or processing failure, skipping (retry later with --only)")
                log(vid, "", comment_text, "error", reason, str(err), False)
                errors += 1
                # Longer pause after a processingFailure, filter may be warming up
                time.sleep(random.uniform(15, 25))
                continue

            print(f"  ERROR ({category}, status {status}, reason '{reason}')")
            log(vid, "", comment_text, "error", reason, str(err), False)
            errors += 1
            time.sleep(random.uniform(5, 10))
            continue

        comment_id = result.get("id", "")
        print(f"  Success. Comment ID: {comment_id}")
        log(vid, comment_id, comment_text, "posted", "", "", False)
        posted += 1

        # Randomized delay between posts to avoid spam filter
        if i < len(items):
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            print(f"  Waiting {delay:.1f}s before next post...")
            time.sleep(delay)

    print()
    print("=" * 70)
    print(f"Done. Posted: {posted}, Skipped: {skipped}, Errors: {errors}")
    print(f"Log: {LOG_FILE}")
    print("=" * 70)

    if errors > 0:
        print()
        print("Some comments failed. To retry failed ones individually:")
        print("  1. Open comments_log.csv")
        print("  2. Find rows with status='error'")
        print("  3. For each video_id, run: python3 post_comments.py --only VIDEO_ID")
        print("  4. Wait a few minutes between retries")
        print("OR just re-run this script, idempotency will retry only the non-posted ones:")
        print("  python3 post_comments.py")

    print()
    print("REMINDER: API cannot pin comments.")
    print("For pinning, the channel owner (or you, if you have Studio access) must click the 3-dot menu on each comment in YouTube Studio and choose Pin.")


if __name__ == "__main__":
    main()
