"""
update_videos.py

Updates title, description, and tags for every video in the configured playlist.

Key features:
- Idempotent: reads update_log.csv at startup, skips already-updated videos
- Retry with exponential backoff on transient errors
- Preserves categoryId, defaultLanguage, defaultAudioLanguage
- Validates title length, description non-empty, tags under limit
- Detects token expiry and exits with clear re-auth instructions
- Skips videos that are inaccessible or have issues, moves to next

Flags:
  --dry-run       Preview changes, don't push
  --limit N       Only process first N videos
  --only VID      Only process this video ID
  --force         Re-process videos already marked successful in log (useful for re-run after revert)

Examples:
  python3 update_videos.py --dry-run
  python3 update_videos.py --limit 1
  python3 update_videos.py             # updates all, skipping already-done
  python3 update_videos.py --only abc123def45
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
    get_video_snippets,
    with_retry,
    classify_error,
    handle_auth_error_and_exit,
    read_completed_ids_from_log,
    append_log,
)

LOG_FILE = "update_log.csv"
LOG_FIELDS = [
    "timestamp", "video_id", "old_title", "new_title",
    "status", "reason", "error_message", "dry_run",
]

TITLE_MAX = 100
DESCRIPTION_MAX = 5000
TAGS_TOTAL_MAX = 500
SUCCESS_STATUSES = {"updated"}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--only", type=str, default=None)
    p.add_argument("--force", action="store_true", help="Re-process videos already in log")
    return p.parse_args()


def build_new_snippet(old_snippet, config):
    """Build the new snippet dict, preserving required and optional fields."""
    old_title = old_snippet.get("title", "")
    new_title = old_title + config["title_suffix"]

    new_snippet = {
        "title": new_title,
        "description": config["description_template"],
        "tags": config["tags"],
        "categoryId": old_snippet.get("categoryId", "22"),
    }

    # Preserve optional language fields if they were set
    if old_snippet.get("defaultLanguage"):
        new_snippet["defaultLanguage"] = old_snippet["defaultLanguage"]
    if old_snippet.get("defaultAudioLanguage"):
        new_snippet["defaultAudioLanguage"] = old_snippet["defaultAudioLanguage"]

    return new_snippet


def validate(new_snippet):
    errors = []
    if len(new_snippet["title"]) > TITLE_MAX:
        errors.append(f"title too long ({len(new_snippet['title'])} chars, max {TITLE_MAX})")
    if len(new_snippet["description"]) > DESCRIPTION_MAX:
        errors.append(f"description too long ({len(new_snippet['description'])} chars, max {DESCRIPTION_MAX})")
    tags_total = sum(len(t) for t in new_snippet["tags"])
    if tags_total > TAGS_TOTAL_MAX:
        errors.append(f"tags total too long ({tags_total} chars, max {TAGS_TOTAL_MAX})")
    if not new_snippet["title"].strip():
        errors.append("title is empty")
    if not new_snippet["description"].strip():
        errors.append("description is empty")
    return errors


def log(video_id, old_title, new_title, status, reason="", error_message="", dry_run=False):
    append_log(LOG_FILE, {
        "timestamp": datetime.now().isoformat(),
        "video_id": video_id,
        "old_title": old_title,
        "new_title": new_title,
        "status": status,
        "reason": reason,
        "error_message": error_message[:500] if error_message else "",
        "dry_run": str(dry_run),
    }, LOG_FIELDS)


def main():
    args = parse_args()
    config = load_config()

    # Header
    print()
    if args.dry_run:
        print("=" * 70)
        print("DRY RUN MODE, no changes will be made to YouTube")
        print("=" * 70)
    else:
        print("=" * 70)
        print("LIVE MODE, changes WILL be made to YouTube")
        print("=" * 70)
        confirm = input("Proceed? Type 'yes' to confirm: ").strip().lower()
        if confirm != "yes":
            print("Cancelled.")
            sys.exit(0)

    youtube = load_youtube_client()

    print()
    print(f"Reading playlist: {config['playlist_name']}")
    items = get_video_ids_in_playlist(youtube, config["playlist_id"])
    print(f"Found {len(items)} videos.")

    # Idempotency: skip videos already successful in the log (unless --force)
    already_done = set()
    if not args.force and not args.dry_run:
        already_done = read_completed_ids_from_log(LOG_FILE, SUCCESS_STATUSES)
        if already_done:
            print(f"Found {len(already_done)} videos already updated in previous runs, will skip.")

    # Apply filters
    if args.only:
        items = [it for it in items if it["video_id"] == args.only]
        if not items:
            print(f"ERROR: Video {args.only} not in this playlist.")
            sys.exit(1)
    else:
        items = [it for it in items if it["video_id"] not in already_done]
        if args.limit:
            items = items[:args.limit]
            print(f"Limit: processing first {args.limit} videos.")

    if not items:
        print("Nothing to process. All videos appear to be already updated.")
        print("If you want to re-process them anyway, use --force.")
        sys.exit(0)

    print(f"Will process {len(items)} videos.")
    print()

    # Fetch current snippets
    video_ids = [it["video_id"] for it in items]
    snippets = get_video_snippets(youtube, video_ids)

    updated = 0
    skipped = 0
    errors = 0

    for i, item in enumerate(items, 1):
        vid = item["video_id"]
        entry = snippets.get(vid)

        if not entry:
            print(f"[{i}/{len(items)}] {vid}: not accessible, skipping")
            log(vid, "", "", "skipped", "video_not_found", "", args.dry_run)
            skipped += 1
            continue

        old_snippet = entry["snippet"]
        old_title = old_snippet.get("title", "")

        new_snippet = build_new_snippet(old_snippet, config)

        print(f"[{i}/{len(items)}] {old_title[:60]}")
        print(f"  New title: {new_snippet['title'][:70]}")
        print(f"  Title length: {len(new_snippet['title'])} chars")

        validation_errors = validate(new_snippet)
        if validation_errors:
            reason = "; ".join(validation_errors)
            print(f"  VALIDATION FAILED: {reason}")
            log(vid, old_title, new_snippet["title"], "skipped", "validation", reason, args.dry_run)
            skipped += 1
            continue

        if args.dry_run:
            print(f"  [DRY RUN] would update")
            log(vid, old_title, new_snippet["title"], "dry_run_ok", "", "", True)
            continue

        # Actual update with retry
        def do_update():
            return youtube.videos().update(
                part="snippet",
                body={"id": vid, "snippet": new_snippet},
            ).execute()

        result, err = with_retry(do_update, max_attempts=3, base_delay=2.0)

        if err is not None:
            category, status, reason = classify_error(err)
            if category == "auth":
                log(vid, old_title, new_snippet["title"], "error", "auth", str(err), False)
                handle_auth_error_and_exit(err)
            else:
                print(f"  ERROR ({category}, status {status}, reason '{reason}'): moving on")
                log(vid, old_title, new_snippet["title"], "error", reason, str(err), False)
                errors += 1
                # Small pause before next video anyway
                time.sleep(random.uniform(1.0, 2.0))
                continue

        print(f"  Success.")
        log(vid, old_title, new_snippet["title"], "updated", "", "", False)
        updated += 1

        # Gentle pacing: 1-2 seconds between updates
        time.sleep(random.uniform(1.0, 2.0))

    print()
    print("=" * 70)
    print(f"Done. Updated: {updated}, Skipped: {skipped}, Errors: {errors}")
    print(f"Log: {LOG_FILE}")
    print("=" * 70)
    if errors > 0:
        print()
        print("Some videos had errors. Re-run the same command:")
        print("  python3 update_videos.py")
        print("The script will skip successfully-updated videos and retry the failed ones.")


if __name__ == "__main__":
    main()
