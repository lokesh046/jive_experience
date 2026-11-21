#!/usr/bin/env bash
# Exercise every endpoint group against a running API.
#
#   make dev PORT=8001            # in one terminal
#   ./scripts/smoke.sh            # in another
#
# Options:
#   BASE_URL=http://localhost:8001  API to hit (default)
#   ADMIN_EMAIL=you@gmail.com       an account with the ADMIN role
#
# This WRITES REAL DATA (a venue, an event, a booking) to whatever database
# `.env` points at. Point DATABASE_URL at a local database first if you do not
# want that in production.

set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8001}"
API="$BASE_URL/api/v1"
ADMIN_EMAIL="${ADMIN_EMAIL:-jivexp@gmail.com}"
CUSTOMER_EMAIL="${CUSTOMER_EMAIL:-demo-customer@example.com}"
PY=".venv/bin/python"
STAMP="$(date +%s)"

pass=0; fail=0; skip=0
bold=$'\033[1m'; green=$'\033[32m'; red=$'\033[31m'; yellow=$'\033[33m'; dim=$'\033[2m'; off=$'\033[0m'

# check <name> <expected-status> <curl args...>
check() {
  local name="$1" expected="$2"; shift 2
  local body status
  body="$(curl -s -w $'\n%{http_code}' "$@")"
  status="${body##*$'\n'}"
  body="${body%$'\n'*}"
  if [[ "$status" == "$expected" ]]; then
    printf '  %s✓%s %-52s %s\n' "$green" "$off" "$name" "$status"
    pass=$((pass+1))
  else
    printf '  %s✗%s %-52s %s (expected %s)\n' "$red" "$off" "$name" "$status" "$expected"
    printf '      %s%s%s\n' "$dim" "${body:0:200}" "$off"
    fail=$((fail+1))
  fi
  LAST_BODY="$body"
}

jq_get() { printf '%s' "$1" | $PY -c "import sys,json;d=json.load(sys.stdin);print(d$2)" 2>/dev/null; }

# check_any <name> <space-separated acceptable statuses> <curl args...>
check_any() {
  local name="$1" expected="$2"; shift 2
  local body status
  body="$(curl -s -w $'\n%{http_code}' "$@")"
  status="${body##*$'\n'}"
  body="${body%$'\n'*}"
  if [[ " $expected " == *" $status "* ]]; then
    printf '  %s✓%s %-52s %s\n' "$green" "$off" "$name" "$status"
    pass=$((pass+1))
  else
    printf '  %s✗%s %-52s %s (expected one of: %s)\n' "$red" "$off" "$name" "$status" "$expected"
    printf '      %s%s%s\n' "$dim" "${body:0:200}" "$off"
    fail=$((fail+1))
  fi
  LAST_BODY="$body"
}

section() { printf '\n%s%s%s\n' "$bold" "$1" "$off"; }

# --------------------------------------------------------------- tokens ---
printf '%sJIVE API smoke test%s  →  %s\n' "$bold" "$off" "$BASE_URL"

if ! curl -sf "$BASE_URL/health" >/dev/null; then
  printf '%s✗ API is not reachable at %s%s\n' "$red" "$BASE_URL" "$off"
  printf '  Start it with:  make dev PORT=%s\n' "${BASE_URL##*:}"
  exit 1
fi

ADMIN_TOKEN="$($PY -m app.cli dev-token --email "$ADMIN_EMAIL" 2>/dev/null | tail -1)"
if [[ -z "$ADMIN_TOKEN" || "$ADMIN_TOKEN" == \#* ]]; then
  printf '%s✗ could not mint an admin token for %s%s\n' "$red" "$ADMIN_EMAIL" "$off"
  printf '  Grant access first:  %s -m app.cli grant-admin --email %s --name "Admin"\n' "$PY" "$ADMIN_EMAIL"
  exit 1
fi
CUSTOMER_TOKEN="$($PY -m app.cli dev-token --email "$CUSTOMER_EMAIL" --create-customer 2>/dev/null | tail -1)"

AUTH_ADMIN=(-H "Authorization: Bearer $ADMIN_TOKEN")
AUTH_CUST=(-H "Authorization: Bearer $CUSTOMER_TOKEN")
JSON=(-H "Content-Type: application/json")

# ---------------------------------------------------------------- system ---
section "System"
check "GET  /health"                     200 "$BASE_URL/health"
check "GET  /system/health/ready"        200 "$API/system/health/ready"
check "GET  /system/info"                200 "$API/system/info"
check "GET  /docs (Swagger UI)"          200 "$BASE_URL/docs"

# ------------------------------------------------------------------ auth ---
section "Authentication"
check "GET  /auth/google/authorize"      200 "$API/auth/google/authorize"
check "POST /auth/google/callback (bad state)" 401 -X POST "$API/auth/google/callback" "${JSON[@]}" \
      -d '{"code":"not-a-real-code","state":"never-issued-state"}'
check "GET  /auth/me (admin)"            200 "$API/auth/me" "${AUTH_ADMIN[@]}"
check "GET  /auth/me (no token)"         401 "$API/auth/me"
check "GET  /auth/me (garbage token)"    401 "$API/auth/me" -H "Authorization: Bearer nonsense"
check "GET  /users/me"                   200 "$API/users/me" "${AUTH_ADMIN[@]}"

# ------------------------------------------------------- admin catalogue ---
section "Admin — catalogue"
check "POST /admin/venues"               201 -X POST "$API/admin/venues" "${AUTH_ADMIN[@]}" "${JSON[@]}" \
      -d "{\"name\":\"Smoke Arena $STAMP\",\"address_line1\":\"1 Test Road\",\"city\":\"Mumbai\",\"state\":\"Maharashtra\",\"postal_code\":\"400001\"}"
VENUE_ID="$(jq_get "$LAST_BODY" "['id']")"

check "GET  /admin/venues"               200 "$API/admin/venues?size=5" "${AUTH_ADMIN[@]}"
check "POST /admin/venues (no auth)"     401 -X POST "$API/admin/venues" "${JSON[@]}" -d '{}'

STARTS="$($PY -c "from datetime import datetime,timedelta,UTC;print((datetime.now(UTC)+timedelta(days=30)).isoformat())")"
check "POST /admin/events"               201 -X POST "$API/admin/events" "${AUTH_ADMIN[@]}" "${JSON[@]}" \
      -d "{\"title\":\"Smoke Test Concert $STAMP\",\"venue_id\":\"$VENUE_ID\",\"starts_at\":\"$STARTS\",\"category\":\"CONCERT\",\"max_tickets_per_customer\":4,\"description\":\"Created by scripts/smoke.sh\"}"
EVENT_ID="$(jq_get "$LAST_BODY" "['id']")"
EVENT_SLUG="$(jq_get "$LAST_BODY" "['slug']")"

check "GET  /admin/events/{id}"          200 "$API/admin/events/$EVENT_ID" "${AUTH_ADMIN[@]}"
check "PATCH /admin/events/{id}"         200 -X PATCH "$API/admin/events/$EVENT_ID" "${AUTH_ADMIN[@]}" "${JSON[@]}" \
      -d '{"subtitle":"An evening of live music"}'
check "POST /admin/events/{id}/publish (no tickets)" 422 -X POST "$API/admin/events/$EVENT_ID/publish" "${AUTH_ADMIN[@]}"

check "POST /admin/.../ticket-categories (General)" 201 -X POST "$API/admin/events/$EVENT_ID/ticket-categories" "${AUTH_ADMIN[@]}" "${JSON[@]}" \
      -d '{"name":"General","price_paise":150000,"capacity":100,"max_per_booking":4,"sort_order":1}'
CATEGORY_ID="$(jq_get "$LAST_BODY" "['id']")"
check "POST /admin/.../ticket-categories (VIP)"     201 -X POST "$API/admin/events/$EVENT_ID/ticket-categories" "${AUTH_ADMIN[@]}" "${JSON[@]}" \
      -d '{"name":"VIP","price_paise":500000,"capacity":20,"max_per_booking":2,"sort_order":0}'
check "PATCH /admin/ticket-categories/{id}"         200 -X PATCH "$API/admin/ticket-categories/$CATEGORY_ID" "${AUTH_ADMIN[@]}" "${JSON[@]}" \
      -d '{"price_paise":175000}'
check "POST /admin/events/{id}/publish"             200 -X POST "$API/admin/events/$EVENT_ID/publish" "${AUTH_ADMIN[@]}"

# -------------------------------------------------------- public catalogue ---
section "Public catalogue"
check "GET  /events"                     200 "$API/events?size=10"
check "GET  /events?city=Mumbai"         200 "$API/events?city=Mumbai&size=10"
check "GET  /events?category=CONCERT"    200 "$API/events?category=CONCERT"
check "GET  /events/cities"              200 "$API/events/cities"
check "GET  /events/{slug}"              200 "$API/events/$EVENT_SLUG"
check "GET  /events/{slug}/availability" 200 "$API/events/$EVENT_SLUG/availability"
check "GET  /events/unknown-slug"        404 "$API/events/no-such-event-anywhere"

# ---------------------------------------------------------------- booking ---
section "Customer — booking"
if [[ -z "$CUSTOMER_TOKEN" ]]; then
  printf '  %s—%s customer token unavailable; booking checks skipped\n' "$yellow" "$off"
  skip=$((skip+4))
else
  check "POST /bookings"                 201 -X POST "$API/bookings" "${AUTH_CUST[@]}" "${JSON[@]}" \
        -d "{\"event_slug\":\"$EVENT_SLUG\",\"items\":[{\"ticket_category_id\":\"$CATEGORY_ID\",\"quantity\":2}],\"idempotency_key\":\"smoke-$STAMP\"}"
  BOOKING_REF="$(jq_get "$LAST_BODY" "['reference']")"

  check "POST /bookings (same idempotency key)" 200 -X POST "$API/bookings" "${AUTH_CUST[@]}" "${JSON[@]}" \
        -d "{\"event_slug\":\"$EVENT_SLUG\",\"items\":[{\"ticket_category_id\":\"$CATEGORY_ID\",\"quantity\":2}],\"idempotency_key\":\"smoke-$STAMP\"}"
  check "POST /bookings (over the per-event limit)" 422 -X POST "$API/bookings" "${AUTH_CUST[@]}" "${JSON[@]}" \
        -d "{\"event_slug\":\"$EVENT_SLUG\",\"items\":[{\"ticket_category_id\":\"$CATEGORY_ID\",\"quantity\":4}]}"
  check "GET  /bookings"                 200 "$API/bookings" "${AUTH_CUST[@]}"
  check "GET  /bookings/{ref}"           200 "$API/bookings/$BOOKING_REF" "${AUTH_CUST[@]}"
  # An admin is not a customer: the role guard answers before the ownership
  # check, so this is 403. Cross-customer access returns 404 and is covered
  # by tests/integration/test_session_security.py.
  check "GET  /bookings/{ref} (admin is not a customer)" 403 "$API/bookings/$BOOKING_REF" "${AUTH_ADMIN[@]}"
  check "GET  /bookings/{ref}/tickets"   200 "$API/bookings/$BOOKING_REF/tickets" "${AUTH_CUST[@]}"
  check "GET  /bookings/{ref}/refund-quote" 200 "$API/bookings/$BOOKING_REF/refund-quote" "${AUTH_CUST[@]}"
  check "GET  /tickets"                  200 "$API/tickets" "${AUTH_CUST[@]}"

  # 503 when no provider is configured; 200 once Razorpay test keys are set
  # and the order is created at the gateway.
  check_any "POST /bookings/{ref}/checkout" "200 503" -X POST "$API/bookings/$BOOKING_REF/checkout" "${AUTH_CUST[@]}"
  CHECKOUT_STATUS_BODY="$LAST_BODY"
fi

# ---------------------------------------------------------------- payments ---
section "Payments"
# Unsigned: 503 with no provider, 401 once Razorpay is configured — either
# way it must never be accepted.
check_any "POST /payments/webhook (unsigned)" "401 503" -X POST "$API/payments/webhook" "${JSON[@]}" -d '{"event":"payment.captured"}'

# ----------------------------------------------------------------- scanner ---
section "Event staff — scanner"
check "GET  /scanner/events (admin)"     200 "$API/scanner/events" "${AUTH_ADMIN[@]}"
check "POST /scanner/scan (invalid QR)"  200 -X POST "$API/scanner/scan" "${AUTH_ADMIN[@]}" "${JSON[@]}" \
      -d "{\"qr_token\":\"definitely-not-a-real-token\",\"event_id\":\"$EVENT_ID\"}"
check "GET  /scanner/.../attendance"     200 "$API/scanner/events/$EVENT_ID/attendance" "${AUTH_ADMIN[@]}"
check "POST /scanner/scan (no auth)"     401 -X POST "$API/scanner/scan" "${JSON[@]}" -d '{}'

# ---------------------------------------------------------- admin commerce ---
section "Admin — commerce"
check "GET  /admin/bookings"             200 "$API/admin/bookings?size=5" "${AUTH_ADMIN[@]}"
check "GET  /admin/events/{id}/staff"    200 "$API/admin/events/$EVENT_ID/staff" "${AUTH_ADMIN[@]}"
check "GET  /admin/events/{id}/attendance" 200 "$API/admin/events/$EVENT_ID/attendance" "${AUTH_ADMIN[@]}"
check "GET  /users (admin only)"         200 "$API/users?size=5" "${AUTH_ADMIN[@]}"
if [[ -n "$CUSTOMER_TOKEN" ]]; then
  check "GET  /users (as customer)"      403 "$API/users" "${AUTH_CUST[@]}"
  check "POST /users/staff (as customer)" 403 -X POST "$API/users/staff" "${AUTH_CUST[@]}" "${JSON[@]}" \
        -d '{"email":"nope@example.com","full_name":"Nope","role":"ADMIN"}'
fi

# ----------------------------------------------------------------- cleanup ---
section "Cleanup"
check "POST /admin/events/{id}/unpublish" 200 -X POST "$API/admin/events/$EVENT_ID/unpublish" "${AUTH_ADMIN[@]}"

# ------------------------------------------------------------------ result ---
printf '\n%s%d passed%s' "$green" "$pass" "$off"
[[ $fail -gt 0 ]] && printf ', %s%d failed%s' "$red" "$fail" "$off"
[[ $skip -gt 0 ]] && printf ', %s%d skipped%s' "$yellow" "$skip" "$off"
printf '\n'
printf '%sTest event:%s %s   (left in the database — delete it when done)\n' "$dim" "$off" "$EVENT_SLUG"
[[ $fail -eq 0 ]] || exit 1
