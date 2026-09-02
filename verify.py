"""
verify.py

Fetches each video's CURRENT state from YouTube via API and prints it.
Use this to prove updates worked, especially since you don't have Studio access.

Output is a human-readable report. Can also save to a text file to share with the channel owner.

Flags:
  --limit N       Only check first N videos
  --only VID      Only check this video
  --save FILE     Save output to a text file (default: verify_report_[timestamp].txt)
"""

import argparse
import sys
from datetime import datetime

from _helpers import (
    load_config,
    load_youtube_client,
    get_video_ids_in_playlist,
    get_video_snippets,
)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--only", type=str, default=None)
    p.add_argument("--save", type=str, default=None)
    p.add_argument("--no-save", action="store_true", help="Print only, don't save file")
    return p.parse_args()


def format_video_report(index, total, video_id, snippet):
    lines = []
    lines.append("=" * 70)
    lines.append(f"Video {index} of {total}")
    lines.append(f"Video ID: {video_id}")
    lines.append(f"Public URL: https://youtube.com/watch?v={video_id}")
    lines.append("")
    lines.append("TITLE:")
    lines.append(snippet.get("title", "<empty>"))
    lines.append("")
    lines.append("DESCRIPTION:")
    lines.append(snippet.get("description", "<empty>"))
    lines.append("")
    lines.append("TAGS:")
    tags = snippet.get("tags", [])
    if tags:
        lines.append(", ".join(tags))
    else:
        lines.append("<no tags>")
    lines.append("")
    lines.append(f"Category ID: {snippet.get('categoryId', '<none>')}")
    if snippet.get("defaultLanguage"):
        lines.append(f"Default language: {snippet['defaultLanguage']}")
    if snippet.get("defaultAudioLanguage"):
        lines.append(f"Default audio language: {snippet['defaultAudioLanguage']}")
    lines.append("")
    return "\n".join(lines)


def main():
    args = parse_args()
    config = load_config()

    youtube = load_youtube_client()

    print(f"Fetching current state from playlist: {config['playlist_name']}")
    items = get_video_ids_in_playlist(youtube, config["playlist_id"])
    print(f"Found {len(items)} videos.")

    if args.only:
        items = [it for it in items if it["video_id"] == args.only]
        if not items:
            print(f"ERROR: Video {args.only} not in this playlist.")
            sys.exit(1)
    elif args.limit:
        items = items[:args.limit]

    video_ids = [it["video_id"] for it in items]
    snippets = get_video_snippets(youtube, video_ids)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    if args.no_save:
        save_file = None
    else:
        save_file = args.save or f"verify_report_{timestamp}.txt"

    output_lines = []
    output_lines.append(f"VERIFICATION REPORT")
    output_lines.append(f"Playlist: {config['playlist_name']}")
    output_lines.append(f"Generated: {timestamp}")
    output_lines.append(f"Video count: {len(items)}")
    output_lines.append("")

    for i, item in enumerate(items, 1):
        vid = item["video_id"]
        entry = snippets.get(vid)
        if not entry:
            output_lines.append(f"Video {i}: {vid} NOT ACCESSIBLE")
            output_lines.append("")
            continue
        output_lines.append(format_video_report(i, len(items), vid, entry["snippet"]))

    full_output = "\n".join(output_lines)

    # Print to console
    print()
    print(full_output)

    if save_file:
        with open(save_file, "w", encoding="utf-8") as f:
            f.write(full_output)
        print()
        print(f"Report saved to: {save_file}")
        print("You can share this file with the channel owner as proof of what's currently live.")


if __name__ == "__main__":
    main()
