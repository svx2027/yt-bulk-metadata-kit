# OAuth setup and authorization

Two parts: what OAuth is and why it's the only acceptable way to do this, and
the concrete steps to authorize the channel owner's channel.

---

## What OAuth actually is

OAuth is a system where a user (the channel owner) gives permission to an app
(this script) to do specific things on their account (manage their YouTube
videos), without ever sharing their password with you.

Analogy: a hotel guest gets a keycard that only opens Room 501 and the gym.
They cannot open the manager's office, cannot access other rooms, cannot clone
more keys. The front desk can deactivate their card anytime. That's OAuth. The
"keycard" is called a token.

**Why not just use their password?**
1. Terms of service violation. Google's ToS forbids account sharing.
2. Security. A password unlocks Gmail, Drive, Photos, everything. This script
   only needs YouTube.
3. Revocation. Sharing a password means revoking access requires changing it,
   which breaks every other Google service they use. With OAuth, revocation is
   one click and only affects this script.

This is what every legitimate YouTube tool (Hootsuite, Buffer, TubeBuddy, etc.)
does.

## Where OAuth "happens" in this project

There's no single "OAuth app" to download. It happens in four places:

1. **Google Cloud Console (browser, one-time).** Create a project, enable the
   YouTube Data API v3, configure the OAuth consent screen, add the channel
   owner as a test user (Testing mode supports up to 100), create an OAuth
   Client ID of type **Desktop app**, and download it as `client_secret.json`.
2. **Your machine, running `auth_setup.py`.** The `google-auth-oauthlib`
   library generates the authorization URL, later exchanges the redirect
   code for a token, and saves it to `token.json`.
3. **The channel owner's browser.** They open the URL you send them, sign in
   as themselves, and see "[Your app name] wants to manage your YouTube
   account, allow or deny." They click Allow. Google then tries to redirect to
   `http://localhost:8080` — which is *your* machine, not theirs, so their
   browser shows a "can't be reached" error page. That's expected: they copy
   that error page's URL and send it back to you.
4. **Back on your machine.** You paste the URL they sent into the running
   `auth_setup.py` prompt. It reads the authorization code out of the URL,
   exchanges it with Google for a token, and saves `token.json`. All future
   script runs read `token.json` and act as their channel.

## Token lifecycle

With the app in **Testing** mode and the `youtube.force-ssl` scope:
- Access token: valid 1 hour, refreshed automatically by the scripts.
- Refresh token: valid **7 days** from the moment the channel owner clicks
  Allow.

For a one-shot batch update this is not a concern — a run of even a few dozen
videos finishes in well under an hour. Coming back after 7 days means repeating
the authorization step (2 minutes of the channel owner's time).

## How the channel owner can revoke access anytime

1. Open https://myaccount.google.com/permissions
2. Find your app in the list
3. Click Remove Access

Takes effect immediately.

---

## Authorizing: step by step

Needs: `client_secret.json` in this folder (from the Cloud Console step
above), and about 2 minutes of the channel owner's time.

**1. Run the script:**
```
python3 auth_setup.py
```

You'll see a long authorization URL printed, then the script will wait at a
`> ` prompt.

**2. Send the URL to the channel owner.** However you communicate — the exact
channel it goes over doesn't matter, only that they receive the full URL
intact. (Some messaging apps mangle very long URLs; if the link looks broken
on their end, resend it as plain text rather than a clickable link.)

**3. What they'll see and do:**
1. They click the link. Their browser opens to a Google sign-in / consent
   screen for their own account.
2. They may see a yellow **"Google hasn't verified this app"** warning. This
   is expected for an app still in Testing mode, not a security problem.
   They click **Advanced**, then the small **"Go to [your app name] (unsafe)"**
   link that appears.
3. Next screen lists the permissions being requested (manage their YouTube
   videos, comments, etc.). They click **Allow**.
4. Their browser redirects to `http://localhost:8080/?state=...&code=...` and
   shows a "site can't be reached" style error. **This is expected** — nothing
   is actually listening on their machine at that address; the code is in the
   URL itself.
5. They copy the **entire** URL from their address bar (not just visible text —
   select-all in the address bar) and send it back to you. They should not
   close the error page before copying.

**4. Paste it back into the waiting `auth_setup.py` prompt and press Enter.**
On success you'll see the token saved and a channel-info sanity check:

```
Token saved to token.json

Testing the token by fetching channel info...
  Channel name: <their channel>
  Channel ID: UCxxxxxxxxxxxxxxxx

All good. You are authorized to manage this channel.
Refresh token valid for 7 days.
```

If `EXPECTED_CHANNEL_NAME_CONTAINS` is set near the top of `auth_setup.py`, the
script warns you if the authorizing account's channel name doesn't match —
catches the common mistake of signing in with a personal account instead of
the channel-owning one.

**5. Confirm the file exists:** `ls token.json`. Treat it like a password —
never share it, never commit it (it's in `.gitignore` already).

For every error message this flow can produce, see
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).
