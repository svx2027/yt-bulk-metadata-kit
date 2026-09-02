"""
auth_setup.py

One-time OAuth authorization flow with the channel owner.

Flow:
1. Generates an authorization URL
2. You send it to the channel owner
3. They authorize, land on an error page, and copy the URL from the address bar
4. You paste that URL here and press Enter
5. Script saves token.json

Token valid for 7 days (Testing mode limit, see OAUTH_SETUP.md). Re-run to refresh.
"""

import json
import os
import sys

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

CLIENT_SECRETS_FILE = "client_secret.json"
TOKEN_FILE = "token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
REDIRECT_URI = "http://localhost:8080/"

# Set this to a substring of the expected channel name (case-insensitive) to get
# a sanity-check warning if the wrong Google account authorizes. Leave empty to
# skip the check.
EXPECTED_CHANNEL_NAME_CONTAINS = ""


def check_preconditions():
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"ERROR: {CLIENT_SECRETS_FILE} not found in this folder.")
        print(f"You're running from: {os.getcwd()}")
        print("Expected: a client_secret.json downloaded from Google Cloud Console (see OAUTH_SETUP.md).")
        sys.exit(1)

    try:
        with open(CLIENT_SECRETS_FILE) as f:
            data = json.load(f)
        if "installed" not in data:
            print(f"ERROR: {CLIENT_SECRETS_FILE} is not a Desktop app credential.")
            print("It must have an 'installed' key at the top level.")
            print("Create a new OAuth Client ID in Google Cloud Console with type 'Desktop app' and replace this file.")
            sys.exit(1)
    except json.JSONDecodeError:
        print(f"ERROR: {CLIENT_SECRETS_FILE} is not valid JSON.")
        print("Re-download it from Google Cloud Console.")
        sys.exit(1)


def main():
    check_preconditions()

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )

    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )

    print()
    print("=" * 70)
    print("STEP 1: Copy the URL below and send it to the channel owner")
    print("=" * 70)
    print()
    print(auth_url)
    print()
    print("=" * 70)
    print()
    print("Waiting for them to authorize. After clicking Allow they will land on")
    print("an error page (This site can't be reached, or similar). That's expected.")
    print("Ask them to copy the ENTIRE URL from their browser address bar and send")
    print("it back to you.")
    print()

    # Loop so user can retry paste if they typo it
    redirect_url = None
    for attempt in range(3):
        raw = input("Paste the URL you were sent here, then press Enter:\n> ").strip()

        if not raw:
            print("  Empty input. Try again.")
            continue

        if not raw.startswith("http://localhost"):
            print()
            print("  That URL doesn't start with http://localhost.")
            print(f"  You pasted: {raw[:80]}...")
            print("  The correct URL looks like: http://localhost:8080/?state=...&code=...")
            print("  Try again.")
            print()
            continue

        if "code=" not in raw:
            print()
            print("  URL is missing the 'code=' parameter, can't proceed.")
            print("  Ask them to re-authorize and copy the full URL.")
            print("  Try again.")
            print()
            continue

        redirect_url = raw
        break

    if redirect_url is None:
        print()
        print("ERROR: Failed to get a valid URL after 3 tries. Aborting.")
        print("Run auth_setup.py again when ready.")
        sys.exit(1)

    print()
    print("Exchanging code for token...")

    try:
        flow.fetch_token(authorization_response=redirect_url)
    except Exception as e:
        err = str(e).lower()
        print()
        if "invalid_grant" in err:
            print("ERROR: Token exchange failed. invalid_grant.")
            print("Likely cause: the auth code already used or expired.")
            print("Fix: re-run auth_setup.py, get a fresh URL, do the exchange again quickly.")
        elif "state" in err:
            print("ERROR: State parameter doesn't match.")
            print("Likely cause: auth_setup.py was run twice in different terminals.")
            print("Fix: close all terminals, open one fresh, cd to the project folder, re-run.")
        elif "redirect_uri_mismatch" in err:
            print("ERROR: Redirect URI mismatch.")
            print("Likely cause: the OAuth client was not created as 'Desktop app' type.")
            print("Fix: recreate the OAuth Client ID in Google Cloud Console with type 'Desktop app'.")
        else:
            print(f"ERROR: {e}")
            print()
            print("Unknown error, see TROUBLESHOOTING.md.")
        sys.exit(1)

    credentials = flow.credentials

    with open(TOKEN_FILE, "w") as f:
        f.write(credentials.to_json())

    print(f"Token saved to {TOKEN_FILE}")
    print()

    # Sanity check: confirm which channel this token controls
    print("Testing the token by fetching channel info...")
    try:
        youtube = build("youtube", "v3", credentials=credentials)
        response = youtube.channels().list(
            part="snippet",
            mine=True,
        ).execute()

        if not response.get("items"):
            print()
            print("ERROR: No channel found for this account.")
            print("The signed-in account doesn't own any YouTube channel.")
            print("Fix: delete token.json (rm token.json), re-run auth_setup.py, confirm the right account signed in.")
            sys.exit(1)

        channel = response["items"][0]
        channel_title = channel["snippet"]["title"]
        channel_id = channel["id"]

        print(f"  Channel name: {channel_title}")
        print(f"  Channel ID: {channel_id}")
        print()

        if not EXPECTED_CHANNEL_NAME_CONTAINS or EXPECTED_CHANNEL_NAME_CONTAINS.lower() in channel_title.lower():
            print("All good. You are authorized to manage this channel.")
            print("Refresh token valid for 7 days.")
        else:
            print(f"WARNING: Channel name is '{channel_title}', not '{EXPECTED_CHANNEL_NAME_CONTAINS}'.")
            print("Did the right account sign in? If not:")
            print("  1. Delete token.json (rm token.json)")
            print("  2. Re-run auth_setup.py")
            print("  3. Confirm with the channel owner which Google account owns the channel.")

    except Exception as e:
        print(f"Token saved but channel check failed: {e}")
        print("The token might still work. Try running snapshot.py to test.")

    print()


if __name__ == "__main__":
    main()
