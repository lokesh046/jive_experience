# Setting up Google OAuth 2.0

What the backend needs from you: a **client ID**, a **client secret**, and the
**redirect URI** registered against them. Nothing else.

Roughly ten minutes. Everything here is free.

---

## 1. Create or pick a Google Cloud project

1. Go to <https://console.cloud.google.com/>.
2. Project dropdown (top bar) → **New Project**.
3. Name it something recognisable, e.g. `jive-events`. → **Create**.
4. Make sure that project is selected before continuing — this is the single
   most common mistake, and it produces credentials that silently belong to
   the wrong project.

## 2. Configure the consent screen

This is the panel users see when they click "Sign in with Google".

1. **APIs & Services → OAuth consent screen**.
2. User type: **External** (anyone with a Google account). → **Create**.
3. Fill in:
   - **App name** — the public, customer-facing name. It appears on the
     consent screen, so use the real brand name.
   - **User support email**
   - **App logo** — optional, but a logo makes the screen look legitimate and
     measurably improves sign-in completion.
   - **Application home page**, **Privacy policy**, **Terms of service** —
     required before you can publish. These are the legal pages listed in
     `docs/open-decisions.md`.
   - **Developer contact email**
4. **Scopes** → *Add or remove scopes* → select exactly these three:
   - `openid`
   - `.../auth/userinfo.email`
   - `.../auth/userinfo.profile`

   Nothing more. Extra scopes trigger Google's verification review, which
   takes weeks, and ask customers for access you do not need.
5. **Test users** — while the app is unpublished only these addresses can sign
   in. Add your own and anyone testing.
6. Save.

## 3. Create the OAuth client

1. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type: **Web application**.
3. Name: `jive-backend` (internal only; never shown to users).
4. **Authorised JavaScript origins** — where the frontend is served:
   ```
   http://localhost:3000          (development)
   https://yourdomain.com         (production)
   ```
5. **Authorised redirect URIs** — where Google sends the user back:
   ```
   http://localhost:3000/auth/google/callback
   https://yourdomain.com/auth/google/callback
   ```

   This must match `GOOGLE_REDIRECT_URI` **exactly** — scheme, host, port,
   path, and no trailing slash. A mismatch gives
   `Error 400: redirect_uri_mismatch`, which is far and away the most common
   problem with this setup.
6. **Create**. Copy the client ID and client secret.

## 4. Put them in the backend

In `backend/.env`:

```bash
GOOGLE_CLIENT_ID=123456789-abcdefg.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-secret-here
GOOGLE_REDIRECT_URI=http://localhost:3000/auth/google/callback
```

No code changes are required. Restart the API and sign-in works.

**The client secret is a server-side secret.** It must never appear in the
frontend bundle, in a `NEXT_PUBLIC_*` variable, or in the repository. The
backend never sends it to the browser — there is a test asserting the
authorization URL does not contain it.

## 5. Check it

```bash
curl -s localhost:8000/api/v1/auth/google/authorize | python3 -m json.tool
```

You should get an `authorization_url` on `accounts.google.com` and a `state`.
Open the URL in a browser: you should see Google's account chooser showing
your app name. After signing in, Google redirects to your callback URL with
`?code=...&state=...`, and the frontend posts both to:

```
POST /api/v1/auth/google/callback
{"code": "...", "state": "..."}
```

which returns the application token pair.

## 6. Before launch: publish the app

While the consent screen is in **Testing**, only listed test users can sign in
and refresh tokens expire after 7 days. Go to **OAuth consent screen →
Publish app** when you are ready.

With only `openid`, `email` and `profile` scopes, publishing does **not**
require Google's verification review. Adding any other scope does.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Error 400: redirect_uri_mismatch` | The redirect URI is not registered, or differs by a character — check scheme, port and trailing slash |
| `Error 403: access_denied` | App is in Testing and this account is not a test user |
| `GOOGLE_NOT_CONFIGURED` from our API | `GOOGLE_CLIENT_ID` or `GOOGLE_CLIENT_SECRET` is missing from `.env` |
| `GOOGLE_CODE_INVALID` | The authorization code was already used or has expired — codes are single-use and short-lived |
| `OAUTH_STATE_INVALID` | The sign-in took longer than `OAUTH_STATE_TTL_SECONDS` (default 10 minutes), the callback was replayed, or Redis is not running |
| `GOOGLE_EMAIL_UNVERIFIED` | Google has not verified that address; we refuse it deliberately, since an unverified address could belong to someone else |

## Granting admin and staff access

**Administrators and event staff sign in with Google too.** There are no
passwords anywhere in this system.

Authority is a property of the account row, not of the credential. The row is
created first, with the role; the person gets that role the next time they
sign in with Google under the matching email.

The very first administrator (there is no admin yet to grant it):

```bash
cd backend
.venv/bin/python -m app.cli grant-admin --email you@gmail.com --name "Your Name"
```

Everyone after that, from the dashboard or the API:

```http
POST /api/v1/users/staff
{"email": "gate@gmail.com", "full_name": "Gate Staff", "role": "EVENT_STAFF"}
```

Notes:

- The email must be **exactly** the address on that person's Google account.
  A typo creates a row nobody can ever sign in to; delete it and redo it.
- If the person already has a customer account (they bought tickets first),
  it is promoted rather than duplicated — they keep their booking history.
- Signing in **never** grants a role. An unknown Google account always becomes
  a CUSTOMER, whatever the address.
- Removing access is a status change on the account, which also revokes every
  live session immediately.

### This makes Google the single point of failure

Two consequences worth stating plainly, because they are now the whole
security model for the dashboard:

1. **Every admin and staff Google account must have two-factor authentication
   enabled.** Whoever controls that Gmail controls the dashboard. There is no
   second factor on our side to fall back on.
2. **If Google is unreachable, nobody can sign in — including you.** There is
   no password path any more. The practical mitigation is that sessions last
   30 days, so an outage does not lock out someone already signed in; a total
   lockout needs server access to resolve.

If the business later wants its own domain (`@jive.events` rather than
personal Gmail), Google Workspace plus the `hd` claim would let the backend
require that domain for privileged accounts. Worth doing before launch, but
it is a purchase decision, not a code change.

## What this does not give you

A Google account is free and unlimited. Sign-in no longer proves one person,
one account — which matters for a 5,000-seat event that sells out in two
minutes. See `anti-bot.md`.
