# JIVE mobile app

Expo (React Native, TypeScript). Customers book and show tickets; gate staff scan and sell at the counter.

## Run it on a phone (Expo Go)

1. API reachable from the phone, on the same Wi-Fi:
   `cd backend && DATABASE_URL=postgresql://jive:jive@localhost:5432/jive_events .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8001`
   and the worker: `make worker`.
2. `cp .env.example .env` and set `EXPO_PUBLIC_API_URL` (and `EXPO_PUBLIC_SITE_URL`) to your computer's address.
3. `npm install`, then `npx expo start`, and open it in Expo Go.

Works in Expo Go: sign-in, events, booking, Razorpay (test mode, in a web view), tickets, QR, scanner, box office.
Needs a development build: Android push, and Razorpay UPI apps if the web view misbehaves.

## Development build (EAS)

`npx eas-cli login`, `npx eas-cli init` (creates the project id), then
`npx eas-cli build --profile development --platform ios` (or `android`).
Edit `eas.json` first: the development profile points at 192.168.1.5; preview and production hold placeholders.
Before store builds: a real bundle id (`com.jive.events` is a placeholder), icon and splash (still Expo's), an Apple key for iOS push.

## What to try, in order

1. Sign in with your email code. 2. Open an event, pick tickets, pay with a Razorpay test netbanking bank.
3. My tickets, open the QR. 4. As staff (assign yourself to an event in admin): Scan tab, scan that QR.
5. Box office: sell one for cash, then one online. 6. Notifications: turn push on (real phone).
