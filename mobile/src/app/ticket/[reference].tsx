import * as Brightness from "expo-brightness";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Alert, FlatList, ScrollView, Text, useWindowDimensions, View } from "react-native";
import QRCode from "react-native-qrcode-svg";
import { SafeAreaView } from "react-native-safe-area-context";
import { Body, Chip, ErrorLine, H1, Label, PillButton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { eventsById } from "@/lib/eventsIndex";
import { inr, longDate, timeOf } from "@/lib/format";
import { STATUS_LABEL, statusTone } from "@/lib/status";
import type { Booking, EventDetail, EventListItem, RefundQuote, Ticket } from "@/lib/types";
import { color, font } from "@/theme";

const CREAM = "#f3e9d2";
const ORANGE = "#e8833a";

export default function TicketScreen() {
  const { reference } = useLocalSearchParams<{ reference: string }>();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const [b, setB] = useState<Booking | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [event, setEvent] = useState<EventListItem | null>(null);
  const [prices, setPrices] = useState<number[]>([]);
  const [page, setPage] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tries, setTries] = useState(0);
  const cardW = width - 40;

  // A bright screen scans faster at the gate. Put it back when leaving.
  useEffect(() => {
    let old: number | null = null;
    (async () => {
      try { old = await Brightness.getBrightnessAsync(); await Brightness.setBrightnessAsync(1); } catch {}
    })();
    return () => { if (old !== null) Brightness.setBrightnessAsync(old).catch(() => {}); };
  }, []);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const booking = await api<Booking>(`bookings/${reference}`);
        if (!live) return;
        setB(booking);
        const [t, ev] = await Promise.all([
          api<Ticket[] | { items: Ticket[] }>(`bookings/${reference}/tickets`).catch(() => []),
          eventsById(),
        ]);
        if (!live) return;
        setTickets(Array.isArray(t) ? t : t.items);
        const found = ev.get(booking.event_id) ?? null;
        setEvent(found);
        if (found) api<EventDetail>(`events/${found.slug}`).then((d) => live && setPrices(d.ticket_categories.map((c) => c.price_paise))).catch(() => {});
      } catch (e) { if (live) setError(e instanceof ApiError ? e.message : "We could not load this booking."); }
    })();
    return () => { live = false; };
  }, [reference]);

  // Tickets are issued a moment after payment: keep checking.
  const live = !!b && (b.status === "CONFIRMED" || b.status === "PARTIALLY_REFUNDED");
  const waiting = live && tickets.length === 0;
  useEffect(() => {
    if (!waiting || tries >= 40) return;
    const id = setTimeout(async () => {
      try {
        const t = await api<Ticket[] | { items: Ticket[] }>(`bookings/${reference}/tickets`);
        const list = Array.isArray(t) ? t : t.items;
        if (list.length) setTickets(list);
      } catch {}
      setTries((n) => n + 1);
    }, 3000);
    return () => clearTimeout(id);
  }, [waiting, tries, reference]);

  async function askCancel() {
    setError(null);
    try {
      const q = await api<RefundQuote>(`bookings/${reference}/refund-quote`);
      const msg = q.eligible ? `You will be refunded ${inr(q.amount_paise)} (${q.percent}%). ${q.reason}` : q.reason || "This booking is not eligible for a refund.";
      Alert.alert("Cancel this booking?", msg, [
        { text: "Keep it", style: "cancel" },
        { text: "Cancel booking", style: "destructive", onPress: cancel },
      ]);
    } catch (e) { setError(e instanceof ApiError ? e.message : "We could not work out the refund."); }
  }
  async function cancel() {
    setBusy(true);
    try {
      setB(await api<Booking>(`bookings/${reference}/cancel`, { method: "POST", json: {} }));
      setTickets((t) => t.map((x) => ({ ...x, qr_token: null, status: "CANCELLED" })));
    } catch (e) { setError(e instanceof ApiError ? e.message : "We could not cancel this booking."); }
    finally { setBusy(false); }
  }

  const upcoming = !!event && new Date(event.starts_at).getTime() > Date.now();
  const topPrice = prices.length > 1 ? Math.max(...prices) : null;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }} edges={["bottom"]}>
      <Stack.Screen options={{ headerShown: true, headerTitle: "", headerTransparent: false, headerStyle: { backgroundColor: color.bg }, headerTintColor: color.white, headerBackButtonDisplayMode: "minimal", headerShadowVisible: false }} />
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
      {!b && !error && <ActivityIndicator color={color.white} style={{ marginTop: 80 }} />}
      {error && !b && <Body style={{ padding: 20 }}>{error}</Body>}
      {b && (
        <FlatList
          data={tickets.length ? tickets : []}
          keyExtractor={(t) => t.id}
          horizontal pagingEnabled showsHorizontalScrollIndicator={false}
          snapToInterval={cardW + 12} decelerationRate="fast"
          onMomentumScrollEnd={(e) => setPage(Math.round(e.nativeEvent.contentOffset.x / (cardW + 12)))}
          contentContainerStyle={{ paddingHorizontal: 20, gap: 12 }}
          ListEmptyComponent={
            <View style={{ width: cardW, padding: 24, borderRadius: 24, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line, gap: 8 }}>
              <Body>{waiting ? "Your tickets are being prepared. This takes a moment." : "There are no tickets on this booking."}</Body>
              {waiting && <ActivityIndicator color={color.white} />}
            </View>
          }
          renderItem={({ item: t, index }) => {
            const item = b.items.find((i) => i.ticket_category_id === t.ticket_category_id);
            const vip = topPrice !== null && !!item && item.unit_price_paise === topPrice;
            return <QrCard t={t} name={item?.category_name ?? "Ticket"} n={index + 1} of={tickets.length} vip={vip} w={cardW} />;
          }}
          style={{ flexGrow: 0 }}
        />
      )}
      {b && (
        <View style={{ padding: 20, gap: 10 }}>
          {tickets.length > 1 && (
            <View accessibilityLabel={`Ticket ${page + 1} of ${tickets.length}`} style={{ flexDirection: "row", gap: 6, justifyContent: "center" }}>
              {tickets.map((t, i) => <View key={t.id} style={{ width: i === page ? 20 : 6, height: 6, borderRadius: 3, backgroundColor: i === page ? color.white : color.line }} />)}
            </View>
          )}
          {event && <H1 style={{ fontSize: 28, lineHeight: 32 }}>{event.title}</H1>}
          {event && <Body style={{ color: color.text }}>{longDate(event.starts_at, event.timezone)}, {timeOf(event.starts_at, event.timezone)}</Body>}
          {event && <Body style={{ fontSize: 14 }}>{event.venue_name}, {event.city}</Body>}
          <View style={{ flexDirection: "row", gap: 10, alignItems: "center", marginTop: 4 }}>
            <Chip label={STATUS_LABEL[b.status] ?? b.status} tone={statusTone(b.status)} />
            <Label>{b.reference} · {inr(b.total_paise)}</Label>
          </View>
          <ErrorLine message={error} />
          {live && upcoming && <PillButton label="Cancel booking" tone="ghost" arrow={false} busy={busy} onPress={askCancel} style={{ marginTop: 8 }} />}
        </View>
      )}
      </ScrollView>
    </SafeAreaView>
  );
}

function QrCard({ t, name, n, of, vip, w }: { t: Ticket; name: string; n: number; of: number; vip: boolean; w: number }) {
  const used = t.status === "CHECKED_IN";
  const valid = !!t.qr_token;
  const paper = vip ? CREAM : color.white;
  return (
    <View style={{ width: w, borderRadius: 28, backgroundColor: paper, padding: 20, gap: 14, alignItems: "center", opacity: valid ? 1 : 0.6 }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignSelf: "stretch", alignItems: "center" }}>
        <Text style={{ fontFamily: font.sansBold, fontSize: 13, letterSpacing: 1.4, textTransform: "uppercase", color: vip ? ORANGE : color.ink }}>{name}</Text>
        <Text style={{ fontFamily: font.sansMedium, fontSize: 13, color: "#555" }}>{n} of {of}</Text>
      </View>
      {valid ? (
        <View accessible accessibilityRole="image" accessibilityLabel={`Entry code for ${name}, ticket ${n} of ${of}`}>
          <QRCode value={t.qr_token!} size={Math.min(w - 80, 260)} color="#0a0a0a" backgroundColor={paper} ecl="M" quietZone={0} />
        </View>
      ) : (
        <View style={{ height: 220, alignItems: "center", justifyContent: "center", paddingHorizontal: 12 }}>
          <Text style={{ fontFamily: font.serif, fontSize: 22, color: color.ink, textAlign: "center" }}>{used ? "This ticket has been scanned." : "This ticket is no longer valid."}</Text>
        </View>
      )}
      <Text style={{ fontFamily: font.sansMedium, fontSize: 12, color: "#555" }}>{t.serial}{valid ? " · Valid until the end of the event" : used ? " · Used" : " · Not valid"}</Text>
    </View>
  );
}
