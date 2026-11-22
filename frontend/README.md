# JIVE frontend

Next.js (App Router, Cache Components) + TypeScript. Talks to the FastAPI backend in `../backend`.

## Run

```bash
cp .env.example .env.local     # API_URL defaults to http://localhost:8001
npm install
npm run dev                    # http://localhost:3000
npm run build && npm start     # what production runs
```

The backend must be running (`make dev PORT=8001` in `../backend`). The build itself does not need it:
pages built without the API render an empty state and refresh once it is up.

## How it is put together

| Concern | Approach |
|---|---|
| Public pages (`/`, `/events/[slug]`) | Prerendered HTML, revalidated every minute. Event data is read with `use cache`, so a traffic spike costs the backend one request per minute, not one per visitor. |
| Live availability | The ticket picker polls `/events/{slug}/availability` every 15 s while the tab is visible. The booking call is the authority. |
| SEO | Per-event title, description, canonical, Open Graph, `MusicEvent` JSON-LD with offers, `sitemap.xml` (built per request), `robots.txt`. Private pages are `noindex` and disallowed. |
| Auth | Google sign-in only. `app/api/[...path]/route.ts` is a same-origin proxy: tokens live in **httpOnly cookies**, never in JavaScript. It refreshes an expired access token once, single-flight, so parallel requests cannot trip the backend's refresh-reuse detection. |
| Money | Integer paise from the API, formatted with `lib/format.ts` (Indian grouping). Totals come from the booking, never recomputed. |
| Holds | The checkout countdown reads the booking's `expires_at`; no duration is hard-coded. |
| Payments | Razorpay Checkout loaded on demand, then `POST /bookings/{ref}/verify`; the page polls until the server confirms. |
| Performance | Fonts self-hosted via `next/font`, local images as WebP via `next/image`, QR library loaded only on the ticket page, city filter runs in the browser. |

## Content that is still placeholder

`lib/content.ts` (artists, archive, private-booking services) and `public/images/*` are generated placeholders at 512px.
Replace them with real photography before launch. The Terms, Privacy and Cancellation pages are stubs awaiting wording.

## Not built yet

Staff scanner, admin screens, enquiry and newsletter forms (no backend endpoints yet).
