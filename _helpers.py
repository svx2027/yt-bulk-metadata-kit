"""
_helpers.py

Shared utilities used by snapshot.py, update_videos.py, post_comments.py,
verify.py, and revert.py.

Centralizes: auth loading, retry logic, error classification, log reading.
"""

import csv
import json
import os
import random
import sys
import time
from functools import wraps

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

TOKEN_FILE = "token.json"
CONFIG_FILE = "config.json"

# Retryable HTTP status codes per YouTube API best practices
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Errors meaning "this specific video, not a system issue"
PER_VIDEO_ERRORS = {
    "commentsDisabled",
    "forbidden",
    "videoNotFound",
    "processingFailure",
    "commentRejected",
    "invalidVideoMetadata",
}

# Errors that mean auth is broken, stop immediately
AUTH_ERRORS = {
    "invalid_grant",
    "invalid_token",
    "unauthorized",
    "authError",
}


def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"ERROR: {CONFIG_FILE} not found.")
        print(f"You're running from: {os.getcwd()}")
        print(f"Expected: a {CONFIG_FILE} in this folder (copy config.example.json and edit it).")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_youtube_client():
    if not os.path.exists(TOKEN_FILE):
        print(f"ERROR: {TOKEN_FILE} not found.")
        print("You haven't run auth_setup.py yet, or the token was deleted.")
        print("Fix: python3 auth_setup.py")
        sys.exit(1)

    try:
        credentials = Credentials.from_authorized_user_file(TOKEN_FILE)
    except Exception as e:
        print(f"ERROR: Could not read {TOKEN_FILE}: {e}")
        print("Token file is corrupted. Re-run auth_setup.py.")
        sys.exit(1)

    # Refresh silently if expired
    if credentials.expired and credentials.refresh_token:
        from google.auth.transport.requests import Request
        try:
            credentials.refresh(Request())
            with open(TOKEN_FILE, "w") as f:
                f.write(credentials.to_json())
            print("Token was expired, refreshed silently.")
        except Exception as e:
            err = str(e).lower()
            if any(ae in err for ae in AUTH_ERRORS):
                print("ERROR: Token expired and cannot be refreshed.")
                print("This happens after 7 days in Testing mode, or if the channel owner revoked access.")
                print("Fix: python3 auth_setup.py (takes about 2 minutes with the channel owner on hand)")
                sys.exit(1)
            print(f"ERROR: Token refresh failed: {e}")
            print("Fix: python3 auth_setup.py")
            sys.exit(1)

    return build("youtube", "v3", credentials=credentials)


def classify_error(http_error):
    """Returns (category, status_code, reason) for an HttpError.
    category is one of: 'retryable', 'auth', 'per_video', 'permanent'.
    """
    status = http_error.resp.status if hasattr(http_error, "resp") else 0

    reason = ""
    try:
        content = json.loads(http_error.content.decode("utf-8"))
        errors = content.get("error", {}).get("errors", [])
        if errors:
            reason = errors[0].get("reason", "")
    except Exception:
        pass

    if reason in AUTH_ERRORS or status == 401:
        return ("auth", status, reason)
    if status in RETRYABLE_STATUS:
        return ("retryable", status, reason)
    if reason in PER_VIDEO_ERRORS:
        return ("per_video", status, reason)
    return ("permanent", status, reason)


def with_retry(func, max_attempts=3, base_delay=2.0):
    """Execute func() with exponential backoff retry on retryable errors.
    Returns (result, error). If successful: (result, None). If failed: (None, HttpError).
    """
    last_error = None
    for attempt in range(max_attempts):
        try:
            return (func(), None)
        except HttpError as e:
            last_error = e
            category, status, reason = classify_error(e)

            if category == "auth":
                # Auth failures: don't retry, bubble up for script to handle
                return (None, e)

            if category == "retryable" and attempt < max_attempts - 1:
                wait = base_delay * (2 ** attempt) + random.uniform(0, 1)
                print(f"  Transient error ({status}), retry in {wait:.1f}s...")
                time.sleep(wait)
                continue

            # Permanent or per-video errors: don't retry, return error
            return (None, e)

    return (None, last_error)


def handle_auth_error_and_exit(http_error):
    """Called when we get an auth error. Prints helpful message and exits."""
    print()
    print("=" * 70)
    print("ERROR: Authentication failed.")
    print("=" * 70)
    print("The token in token.json is expired or invalid.")
    print("This happens after 7 days in Testing mode, or if the channel owner revoked access.")
    print()
    print("Fix: python3 auth_setup.py")
    print("Then re-run the current script. It will resume where it left off.")
    print("=" * 70)
    sys.exit(1)


def read_completed_ids_from_log(log_file, success_statuses):
    """Returns a set of video_ids that have status in success_statuses in the log file.
    Used for idempotency: skip these on re-run.
    """
    if not os.path.exists(log_file):
        return set()
    completed = set()
    try:
        with open(log_file, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("status") in success_statuses and row.get("dry_run") == "False":
                    completed.add(row.get("video_id"))
    except Exception:
        # If log is corrupted, don't skip anything (safer to re-attempt than to skip)
        pass
    return completed


def append_log(log_file, row_dict, fieldnames):
    """Append a row to a CSV log, creating the file and header if needed."""
    is_new = not os.path.exists(log_file)
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new:
            writer.writeheader()
        writer.writerow(row_dict)


def get_video_ids_in_playlist(youtube, playlist_id):
    """Returns list of (video_id, playlist_item_title) tuples in playlist order."""
    items = []
    next_page_token = None
    while True:
        response, err = with_retry(lambda: youtube.playlistItems().list(
            part="contentDetails,snippet",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=next_page_token,
        ).execute())
        if err:
            category, status, reason = classify_error(err)
            if category == "auth":
                handle_auth_error_and_exit(err)
            raise err
        for item in response["items"]:
            items.append({
                "video_id": item["contentDetails"]["videoId"],
                "title": item["snippet"]["title"],
            })
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break
    return items


def get_video_snippets(youtube, video_ids):
    """Fetch full snippet for each video_id. Returns dict {video_id: snippet}."""
    snippets = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        response, err = with_retry(lambda: youtube.videos().list(
            part="snippet,status",
            id=",".join(batch),
        ).execute())
        if err:
            category, _, _ = classify_error(err)
            if category == "auth":
                handle_auth_error_and_exit(err)
            raise err
        for item in response["items"]:
            snippets[item["id"]] = {
                "snippet": item["snippet"],
                "status": item.get("status", {}),
            }
    return snippets
