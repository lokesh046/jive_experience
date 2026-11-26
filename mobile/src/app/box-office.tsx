import { Stack } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import QRCode from "react-native-qrcode-svg";
import { SafeAreaView } from "react-native-safe-area-context";
import { RazorpaySheet, type PayResult } from "@/components/RazorpaySheet";
import { Body, ErrorLine, H1, H2, Label, PillButton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { razorpayHtml } from "@/lib/booking";
import { inr } from "@/lib/format";
import type { AssignedEvent, Booking, CheckoutResponse, EventDetail, Ticket } from "@/lib/types";
import { color, font } from "@/theme";

type Method = "CASH" | "ONLINE";
type Step = "sell" | "collect" | "paying" | "tickets";
interface SaleOut { booking: Booking; tickets: Ticket[] }
interface SellerRow { seller_id: string; seller_name: string | null; cash_tickets: number; cash_paise: number; online_tickets: number; online_paise: number }

const input = { height: 52, borderRadius: 26, paddingHorizontal: 20, backgroundColor: color.surface, color: color.white, fontFamily: font.sans, fontSize: 16, borderWidth: 1, borderColor: color.line } as const;

export default function BoxOffice() {
  const [events, setEvents] = useState<AssignedEvent[] | null>(null);
  const [event, setEvent] = useState<AssignedEvent | null>(null);
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [cat, setCat] = useState<string | null>(null);
  const [qty, setQty] = useState(1);
  const [method, setMethod] = useState<Method>("CASH");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [step, setStep] = useState<Step>("sell");
  const [booking, setBooking] = useState<Booking | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sales, setSales] = useState<SellerRow[]>([]);
  const [pay, setPay] = useState<string | null>(null);
  const poll = useRef(0);

  useEffect(() => {
    api<AssignedEvent[]>("scanner/events")
      .then((l) => { setEvents(l); if (l.length === 1) setEvent(l[0]); })
      .catch((e) => { setEvents([]); setError(e instanceof ApiError ? e.message : "Could not load your events."); });
  }, []);

  const loadSales = useCallback((id: string) => {
    api<SellerRow[]>(`box-office/events/${id}/summary`).then(setSales).catch(() => {});
  }, []);

  useEffect(() => {
    if (!event) return;
    api<EventDetail>(`events/${event.slug}`).then((d) => {
      setDetail(d);
      setCat(d.ticket_categories.find((c) => !c.is_sold_out)?.id ?? null);
    }).catch(() => setError("Could not load this event's tickets."));
    loadSales(event.event_id);
  }, [event, loadSales]);

  const chosen = detail?.ticket_categories.find((c) => c.id === cat) ?? null;
  const total = chosen ? chosen.price_paise * qty : 0;

  // Wait for the worker to issue the tickets, then show them.
  const waitForTickets = useCallback(async (reference: string) => {
    const run = ++poll.current;
    for (let i = 0; i < 30 && run === poll.current; i++) {
      try {
        const r = await api<SaleOut>(`box-office/bookings/${reference}`);
        if (r.tickets.length > 0) { setBooking(r.booking); setTickets(r.tickets); setStep("tickets"); if (event) loadSales(event.event_id); return; }
      } catch {}
      await new Promise((res) => setTimeout(res, 1500));
    }
    setError("The tickets are taking longer than usual. Open this sale again in a moment.");
  }, [event, loadSales]);

  async function sell() {
    if (!event || !chosen) return;
    setBusy(true); setError(null);
    try {
      const b = await api<Booking>(`box-office/events/${event.event_id}/sales`, {
        method: "POST",
        json: { ticket_category_id: chosen.id, quantity: qty, method, buyer_name: name, buyer_phone: phone, buyer_email: email },
      });
      setBooking(b);
      if (b.status === "CONFIRMED") { setStep("paying"); void waitForTickets(b.reference); }
      else setStep("collect");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the sale. Please try again.");
    } finally { setBusy(false); }
  }

  async function verify(ref: string, r: PayResult) {
    setPay(null); setStep("paying");
    try {
      await api<Booking>(`box-office/bookings/${ref}/verify`, { method: "POST", json: { provider_payment_id: r.razorpay_payment_id, provider_order_id: r.razorpay_order_id, signature: r.razorpay_signature } });
    } catch { /* the webhook may still confirm it; keep checking */ }
    void waitForTickets(ref);
  }

  async function collect() {
    if (!booking) return;
    setBusy(true); setError(null);
    try {
      const co = await api<CheckoutResponse>(`box-office/bookings/${booking.reference}/checkout`, { method: "POST" });
      setPay(razorpayHtml({ ...co.checkout_payload, prefill: { name: name || undefined, contact: phone || undefined, email: email || undefined }, theme: { color: "#000000" } }));
    } catch (e) { setError(e instanceof ApiError ? e.message : "Could not open the payment window."); }
    finally { setBusy(false); }
  }

  function again() {
    poll.current++;
    setStep("sell"); setBooking(null); setTickets([]); setQty(1); setName(""); setPhone(""); setEmail(""); setError(null); setBusy(false);
    if (event) { loadSales(event.event_id); api<EventDetail>(`events/${event.slug}`).then(setDetail).catch(() => {}); }
  }

  const mine = sales.reduce((a, r) => ({ cash: a.cash + r.cash_paise, online: a.online + r.online_paise, n: a.n + r.cash_tickets + r.online_tickets }), { cash: 0, online: 0, n: 0 });

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }} edges={["bottom"]}>
      <Stack.Screen options={{ headerShown: true, headerTitle: "", headerStyle: { backgroundColor: color.bg }, headerTintColor: color.white, headerShadowVisible: false, headerBackButtonDisplayMode: "minimal" }} />
      <ScrollView contentContainerStyle={{ padding: 20, gap: 14, paddingBottom: 48 }} keyboardShouldPersistTaps="handled">
        <H1>Box office</H1>

        {events === null && <Body>Loading…</Body>}
        {events && events.length === 0 && <Body>{error ?? "You are not assigned to any events yet."}</Body>}

        {events && !event && events.length > 0 && (
          <>
            <Body>Choose the event you are selling for.</Body>
            {events.map((e) => (
              <Pressable key={e.event_id} onPress={() => setEvent(e)} accessibilityRole="button" style={{ padding: 16, borderRadius: 20, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line, gap: 4 }}>
                <Text style={{ fontFamily: font.serif, fontSize: 22, color: color.white }}>{e.title}</Text>
                <Body style={{ fontSize: 14 }}>{e.venue_name}, {e.city}</Body>
              </Pressable>
            ))}
          </>
        )}

        {event && (
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            <Body style={{ color: color.text, flex: 1 }}>{event.title}</Body>
            {events && events.length > 1 && step === "sell" && <Pressable onPress={() => { setEvent(null); setDetail(null); setCat(null); }} accessibilityRole="button"><Text style={{ fontFamily: font.sansMedium, color: color.white }}>Change</Text></Pressable>}
          </View>
        )}

        {event && step === "sell" && detail && (
          <>
            <Label>Ticket</Label>
            {detail.ticket_categories.map((c) => {
              const on = cat === c.id;
              return (
                <Pressable key={c.id} disabled={c.is_sold_out} onPress={() => setCat(c.id)} accessibilityRole="radio" accessibilityState={{ selected: on, disabled: c.is_sold_out }}
                  style={{ flexDirection: "row", justifyContent: "space-between", padding: 16, borderRadius: 20, backgroundColor: color.surface, borderWidth: on ? 2 : 1, borderColor: on ? color.white : color.line, opacity: c.is_sold_out ? 0.5 : 1 }}>
                  <Text style={{ fontFamily: font.sansBold, fontSize: 16, color: color.white }}>{c.name}</Text>
                  <Text style={{ fontFamily: font.serif, fontSize: 20, color: color.white }}>{c.is_sold_out ? "Sold out" : inr(c.price_paise)}</Text>
                </Pressable>
              );
            })}

            <Label>How many</Label>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 20 }}>
              <Round label="One fewer" glyph="−" onPress={() => setQty((q) => Math.max(1, q - 1))} />
              <Text accessibilityLiveRegion="polite" style={{ fontFamily: font.serif, fontSize: 34, color: color.white, minWidth: 40, textAlign: "center" }}>{qty}</Text>
              <Round label="One more" glyph="+" onPress={() => setQty((q) => Math.min(chosen?.max_per_booking ?? 10, q + 1))} />
            </View>

            <Label>Paid by</Label>
            <View accessibilityRole="radiogroup" style={{ flexDirection: "row", padding: 4, borderRadius: 999, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line }}>
              {(["CASH", "ONLINE"] as const).map((m) => (
                <Pressable key={m} onPress={() => setMethod(m)} accessibilityRole="radio" accessibilityState={{ selected: method === m }}
                  style={{ flex: 1, height: 44, borderRadius: 999, alignItems: "center", justifyContent: "center", backgroundColor: method === m ? color.white : "transparent" }}>
                  <Text style={{ fontFamily: font.sansBold, color: method === m ? color.ink : color.muted }}>{m === "CASH" ? "Cash" : "UPI / card"}</Text>
                </Pressable>
              ))}
            </View>

            <Label>Buyer (optional)</Label>
            <TextInput accessibilityLabel="Buyer name" placeholder="Name" placeholderTextColor={color.faint} value={name} onChangeText={setName} maxLength={120} style={input} />
            <TextInput accessibilityLabel="Buyer phone" placeholder="Phone" placeholderTextColor={color.faint} keyboardType="phone-pad" value={phone} onChangeText={setPhone} maxLength={20} style={input} />
            <TextInput accessibilityLabel="Buyer email" placeholder="Email, to also send the tickets" placeholderTextColor={color.faint} keyboardType="email-address" autoCapitalize="none" value={email} onChangeText={setEmail} style={input} />

            <ErrorLine message={error} />
            <PillButton label={method === "CASH" ? `Take ${inr(total)} cash and issue` : `Charge ${inr(total)}`} onPress={sell} busy={busy} disabled={!chosen} />
          </>
        )}

        {step === "collect" && booking && (
          <>
            <H2>Collect {inr(booking.total_paise)}</H2>
            <Body>Sale {booking.reference}. Take the payment from the buyer now, by UPI or card.</Body>
            <ErrorLine message={error} />
            <PillButton label={`Collect ${inr(booking.total_paise)}`} onPress={collect} busy={busy} />
            <PillButton label="Start over" tone="ghost" arrow={false} onPress={again} />
          </>
        )}

        {step === "paying" && (
          <View style={{ gap: 10, marginTop: 20 }}>
            <H2>Issuing tickets…</H2>
            <Body>This takes a few seconds.</Body>
            <ErrorLine message={error} />
            {!!error && <PillButton label="Start a new sale" tone="ghost" arrow={false} onPress={again} />}
          </View>
        )}

        {step === "tickets" && booking && (
          <>
            <H2>Sold. Show the buyer:</H2>
            <Label>{booking.reference} · {inr(booking.total_paise)}</Label>
            {tickets.map((t, i) => {
              const item = booking.items.find((x) => x.ticket_category_id === t.ticket_category_id);
              return (
                <View key={t.id} style={{ borderRadius: 24, backgroundColor: color.white, padding: 20, alignItems: "center", gap: 10 }}>
                  <Text style={{ alignSelf: "stretch", fontFamily: font.sansBold, fontSize: 13, letterSpacing: 1.2, textTransform: "uppercase", color: color.ink }}>{item?.category_name ?? "Ticket"} · {i + 1} of {tickets.length}</Text>
                  {t.qr_token && <QRCode value={t.qr_token} size={220} color="#0a0a0a" backgroundColor="#ffffff" ecl="M" quietZone={0} />}
                  <Text style={{ fontFamily: font.sansMedium, fontSize: 12, color: "#555" }}>{t.serial}</Text>
                </View>
              );
            })}
            <PillButton label="Next sale" onPress={again} />
          </>
        )}

        {event && (
          <View style={{ marginTop: 12, padding: 16, borderRadius: 20, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line, gap: 8 }}>
            <Text style={{ fontFamily: font.sansBold, color: color.white }}>{mine.n} sold{sales.length > 0 ? ` · cash to hand in ${inr(mine.cash)}` : ""}</Text>
            {sales.length === 0 ? <Body style={{ fontSize: 14 }}>No sales yet.</Body> : sales.map((r) => (
              <View key={r.seller_id} style={{ gap: 2 }}>
                <Text style={{ fontFamily: font.sansMedium, color: color.text }}>{r.seller_name ?? "Seller"}</Text>
                <Body style={{ fontSize: 13 }}>Cash {r.cash_tickets} · {inr(r.cash_paise)}   Online {r.online_tickets} · {inr(r.online_paise)}</Body>
              </View>
            ))}
          </View>
        )}
      </ScrollView>

      <RazorpaySheet html={pay} onSuccess={(r) => booking && verify(booking.reference, r)} onFailed={() => { setPay(null); setError("That payment did not go through. Try again, or start over and take cash."); }} onClose={() => setPay(null)} />
    </SafeAreaView>
  );
}

function Round({ label, glyph, onPress }: { label: string; glyph: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label} hitSlop={8}
      style={{ width: 56, height: 56, borderRadius: 28, borderWidth: 1, borderColor: color.line, alignItems: "center", justifyContent: "center" }}>
      <Text style={{ fontFamily: font.sans, fontSize: 28, color: color.white }}>{glyph}</Text>
    </Pressable>
  );
}
