import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Linking, Modal, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { WebView } from "react-native-webview";
import { Body, Chip, ErrorLine, H1, H2, Label, PillButton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { forgetKey, razorpayHtml } from "@/lib/booking";
import { useAuth } from "@/lib/auth";
import { API_V1 } from "@/lib/config";
import { inr } from "@/lib/format";
import type { Booking, CheckoutResponse } from "@/lib/types";
import { color, font } from "@/theme";

type View_ = "loading" | "review" | "processing" | "failed" | "expired";
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

export default function Checkout() {
  const { reference, title, when, venue } = useLocalSearchParams<{ reference: string; title?: string; when?: string; venue?: string }>();
  const { user } = useAuth();
  const router = useRouter();
  const [b, setB] = useState<Booking | null>(null);
  const [view, setView] = useState<View_>("loading");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pay, setPay] = useState<string | null>(null);   // the Razorpay page, while it is open
  const [left, setLeft] = useState<number | null>(null);
  const polling = useRef(false);

  const done = useCallback(() => {
    forgetKey();
    router.replace({ pathname: "/confirmed/[reference]", params: { reference, title, when, venue } });
  }, [router, reference, title, when, venue]);

  const apply = useCallback((x: Booking) => {
    setB(x);
    if (x.status === "CONFIRMED" || x.status === "PARTIALLY_REFUNDED") return done();
    if (x.status === "PENDING") return setView((v) => (v === "processing" || v === "failed" ? v : "review"));
    forgetKey();
    setView("expired");
  }, [done]);

  useEffect(() => {
    api<Booking>(`bookings/${reference}`).then(apply).catch((e) => { setError(e?.message ?? "Could not load this booking."); setView("expired"); });
  }, [reference, apply]);

  // Counts down to the hold's own expiry, never a fixed duration.
  useEffect(() => {
    if (!b?.expires_at || b.status !== "PENDING") return;
    const tick = () => {
      const s = Math.max(0, Math.round((new Date(b.expires_at!).getTime() - Date.now()) / 1000));
      setLeft(s);
      if (s === 0 && view !== "processing") { forgetKey(); setView("expired"); }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [b, view]);

  // After paying the server confirms on its own time: keep asking.
  const poll = useCallback(async () => {
    if (polling.current) return;
    polling.current = true;
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const x = await api<Booking>(`bookings/${reference}`);
        if (x.status !== "PENDING") { polling.current = false; return apply(x); }
      } catch {}
    }
    polling.current = false;
    setError("This is taking longer than usual. Your payment is safe: check My tickets in a few minutes.");
  }, [reference, apply]);

  async function verify(r: { razorpay_payment_id: string; razorpay_order_id: string; razorpay_signature: string }) {
    setPay(null); setView("processing");
    try {
      const x = await api<Booking>(`bookings/${reference}/verify`, { method: "POST", json: { provider_payment_id: r.razorpay_payment_id, provider_order_id: r.razorpay_order_id, signature: r.razorpay_signature } });
      apply(x);
      if (x.status === "PENDING") void poll();
    } catch { void poll(); }   // the webhook may still confirm it
  }

  /** Ask the server whether this booking was paid. The sheet can close before we hear the result. */
  const sync = useCallback(async (): Promise<boolean> => {
    try {
      const x = await api<Booking>(`bookings/${reference}/sync`, { method: "POST" });
      if (x.status !== "PENDING") { apply(x); return true; }
    } catch {}
    return false;
  }, [reference, apply]);

  /** A web view cannot open upi:// or intent:// links: hand them to the phone's payment apps. */
  function openElsewhere(req: { url: string }): boolean {
    if (/^(https?|about|data|blob|file):/i.test(req.url)) return true;
    let target = req.url;
    const m = req.url.match(/^intent:\/\/(.*?)#Intent;.*?scheme=([a-z0-9.+-]+)/i);
    if (m) target = `${m[2]}://${m[1]}`;
    Linking.openURL(target).catch(() => setError("No payment app on this phone could open that. Choose another way to pay."));
    return false;
  }

  function closeSheet() { setPay(null); void sync(); }

  async function startPay() {
    setBusy(true); setError(null);
    try {
      if (await sync()) return;   // already paid: no second window
      const co = await api<CheckoutResponse>(`bookings/${reference}/checkout`, { method: "POST" });
      setPay(razorpayHtml({
        ...co.checkout_payload,
        prefill: { email: user?.email, contact: user?.phone_e164 ?? undefined, name: user?.full_name ?? undefined },
        theme: { color: "#000000" },
        // Netbanking, UPI and 3-D Secure leave the page, so the result comes back by redirect.
        redirect: true,
        callback_url: `${API_V1}/payments/razorpay/return`,
      }));
    } catch (e) {
      if (e instanceof ApiError && e.code === "BOOKING_EXPIRED") { setView("expired"); return; }
      setError(e instanceof ApiError ? e.message : "We could not open the payment window. Please try again.");
    } finally { setBusy(false); }
  }

  function onMessage(raw: string) {
    let m: any; try { m = JSON.parse(raw); } catch { return; }
    if (m.type === "success") void verify(m.payload);
    else if (m.type === "failed") { setPay(null); setView("failed"); }
    else if (m.type === "dismissed") closeSheet();
    else if (m.type === "error") { closeSheet(); setError("We could not open the payment window. Please try again."); }
  }

  const holdable = view === "review" || view === "failed";

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }}>
      <Stack.Screen options={{ headerShown: false }} />
      <ScrollView contentContainerStyle={{ padding: 20, gap: 16, flexGrow: 1 }}>
        {view === "loading" && <ActivityIndicator color={color.white} style={{ marginTop: 80 }} />}

        {view === "processing" && (
          <View style={{ marginTop: 80, gap: 12, alignItems: "center" }}>
            <ActivityIndicator color={color.white} />
            <H2>Confirming your payment</H2>
            <Body style={{ textAlign: "center" }}>Please keep this screen open. It takes a few seconds.</Body>
            <ErrorLine message={error} />
            {!!error && <PillButton label="See my tickets" arrow={false} tone="ghost" onPress={() => router.replace("/tickets")} style={{ alignSelf: "stretch" }} />}
          </View>
        )}

        {view === "expired" && (
          <View style={{ marginTop: 60, gap: 12 }}>
            <H1>Your hold has ended</H1>
            <Body>{error ?? "The tickets went back on sale. You have not been charged."}</Body>
            <PillButton label="Back to events" onPress={() => router.replace("/events")} style={{ marginTop: 12 }} />
          </View>
        )}

        {holdable && b && (
          <>
            <H1>Review and pay</H1>
            {left !== null && <View><Chip label={`Seats held ${mmss(left)}`} tone={left < 60 ? "warn" : "neutral"} /></View>}
            {view === "failed" && <ErrorLine message="That payment did not go through. You have not been charged. Try again." />}

            <View style={{ padding: 18, borderRadius: 24, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line, gap: 10 }}>
              {!!title && <Text style={{ fontFamily: font.serif, fontSize: 22, color: color.white }}>{title}</Text>}
              {!!when && <Body style={{ fontSize: 14 }}>{when}</Body>}
              {!!venue && <Body style={{ fontSize: 14 }}>{venue}</Body>}
              <View style={{ height: 1, backgroundColor: color.line, marginVertical: 4 }} />
              {b.items.map((i) => <Row key={i.ticket_category_id} l={`${i.quantity} × ${i.category_name}`} r={inr(i.line_total_paise)} />)}
              {b.fees_paise > 0 && <Row l="Fees" r={inr(b.fees_paise)} />}
              {!!b.discount_paise && b.discount_paise > 0 && <Row l="Promo" r={`−${inr(b.discount_paise)}`} good />}
              <View style={{ height: 1, backgroundColor: color.line, marginVertical: 4 }} />
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" }}>
                <Label>Total</Label>
                <Text style={{ fontFamily: font.serif, fontSize: 30, color: color.white }}>{inr(b.total_paise)}</Text>
              </View>
            </View>

            <ErrorLine message={error} />
            <PillButton label={`Pay ${inr(b.total_paise)}`} onPress={startPay} busy={busy} />
            <Body style={{ fontSize: 13, textAlign: "center" }}>Secure payment by Razorpay. UPI, cards and netbanking.</Body>
            <Pressable onPress={() => router.back()} accessibilityRole="button"><Body style={{ textAlign: "center", textDecorationLine: "underline" }}>Change tickets</Body></Pressable>
          </>
        )}
      </ScrollView>

      <Modal visible={pay !== null} animationType="slide" onRequestClose={closeSheet}>
        <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: 20, paddingVertical: 12 }}>
            <Text style={{ fontFamily: font.sansBold, color: color.white }}>Payment</Text>
            <Pressable onPress={closeSheet} accessibilityRole="button" hitSlop={10}><Text style={{ fontFamily: font.sansMedium, color: color.muted }}>Close</Text></Pressable>
          </View>
          {pay && (
            <WebView
              originWhitelist={["*"]}
              source={{ html: pay, baseUrl: "https://checkout.razorpay.com" }}
              onMessage={(ev) => onMessage(ev.nativeEvent.data)}
              onShouldStartLoadWithRequest={openElsewhere}
              javaScriptEnabled domStorageEnabled setSupportMultipleWindows={false}
              style={{ flex: 1, backgroundColor: color.bg }}
            />
          )}
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

function Row({ l, r, good }: { l: string; r: string; good?: boolean }) {
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
      <Text style={{ fontFamily: font.sans, fontSize: 15, color: color.muted }}>{l}</Text>
      <Text style={{ fontFamily: font.sansMedium, fontSize: 15, color: good ? color.good : color.text }}>{r}</Text>
    </View>
  );
}
