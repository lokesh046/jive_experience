import { Image } from "expo-image";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { TicketPicker, usePicker } from "@/components/TicketPicker";
import { Body, Chip, ErrorLine, H1, H2, Label, PillButton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { BOOKING_MESSAGES, idempotencyKey } from "@/lib/booking";
import { inr, longDate, timeOf } from "@/lib/format";
import type { Booking, EventDetail } from "@/lib/types";
import { color, font } from "@/theme";

export default function EventScreen() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const router = useRouter();
  const [e, setE] = useState<EventDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const p = usePicker(e);
  const [busy, setBusy] = useState(false);
  const [bookError, setBookError] = useState<string | null>(null);
  const sellable = !!e && e.on_sale && !e.is_past && e.status !== "CANCELLED";

  useEffect(() => {
    api<EventDetail>(`events/${slug}`).then(setE).catch((x) => setError(x?.message ?? "Could not load this event."));
  }, [slug]);

  async function reserve() {
    if (!e || !p.cat) return;
    setBusy(true); setBookError(null);
    const items = [{ ticket_category_id: p.cat.id, quantity: p.count }];
    const sig = JSON.stringify({ items, promo: p.promo?.code ?? null });
    try {
      const b = await api<Booking>("bookings", { method: "POST", json: { event_slug: e.slug, items, promo_code: p.promo?.code ?? null, idempotency_key: idempotencyKey(sig) } });
      router.push({ pathname: "/checkout/[reference]", params: { reference: b.reference, title: e.title, when: `${longDate(e.starts_at, e.timezone)}, ${timeOf(e.starts_at, e.timezone)}`, venue: `${e.venue.name}, ${e.venue.city}` } });
    } catch (x) {
      if (x instanceof ApiError && x.code === "PHONE_NUMBER_REQUIRED") router.push("/phone");
      else setBookError(x instanceof ApiError ? (BOOKING_MESSAGES[x.code] ?? x.message) : "Something went wrong. Please try again.");
    } finally { setBusy(false); }
  }

  const closed = e?.is_past ? "This night has passed. Tickets are no longer on sale."
    : e?.status === "CANCELLED" ? "This event has been cancelled."
    : e?.is_sold_out ? "This event is sold out." : "Tickets are not on sale right now.";

  return (
    <View style={{ flex: 1, backgroundColor: color.bg }}>
      <Stack.Screen options={{ headerShown: true, headerTransparent: true, headerTitle: "", headerTintColor: color.white, headerBackButtonDisplayMode: "minimal" }} />
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 48 }} keyboardShouldPersistTaps="handled">
        {error && <Body style={{ padding: 20, paddingTop: 100 }}>{error}</Body>}
        {e && (
          <>
            <Image source={e.banner_image_url ?? e.thumbnail_image_url} style={{ width: "100%", height: 340 }} contentFit="cover" />
            <View style={{ padding: 20, gap: 10 }}>
              {e.is_past && <Chip label="Past event" />}
              {e.status === "CANCELLED" && <Chip label="Cancelled" tone="bad" />}
              <H1>{e.title}</H1>
              <Body style={{ color: color.text }}>{longDate(e.starts_at, e.timezone)}, {timeOf(e.starts_at, e.timezone)}</Body>
              <Body>{e.venue.name}, {e.venue.city}</Body>

              {!!e.description && (
                <View style={{ marginTop: 20, gap: 10 }}>
                  <H2>The night</H2>
                  {e.description.split(/\n{2,}/).map((t, i) => <Body key={i}>{t.trim()}</Body>)}
                </View>
              )}

              {e.lineup.length > 0 && (
                <View style={{ marginTop: 20, gap: 8 }}>
                  <Label>Lineup</Label>
                  {e.lineup.map((l, i) => (
                    <Text key={i} style={{ fontFamily: font.serif, fontSize: 20, color: color.white }}>{l.name}{l.role ? <Text style={{ fontFamily: font.sans, fontSize: 14, color: color.muted }}>  {l.role}</Text> : null}</Text>
                  ))}
                </View>
              )}

              <View style={{ marginTop: 24 }}>
                {sellable ? <TicketPicker e={e} p={p} /> : <Body>{closed}</Body>}
              </View>
            </View>
          </>
        )}
      </ScrollView>
      {sellable && p.cat && (
        <SafeAreaView edges={["bottom"]} style={{ backgroundColor: color.bg, borderTopWidth: 1, borderTopColor: color.line, paddingHorizontal: 20, paddingTop: 12, gap: 8 }}>
          <ErrorLine message={bookError} />
          <View style={{ flexDirection: "row", alignItems: "center", gap: 14 }}>
            <View>
              <Text style={{ fontFamily: font.sans, fontSize: 12, color: color.muted }}>{p.count} × {p.cat.name}</Text>
              <Text style={{ fontFamily: font.serif, fontSize: 26, color: color.white }}>{inr(p.total)}</Text>
            </View>
            <PillButton label="Continue" onPress={reserve} busy={busy} style={{ flex: 1 }} />
          </View>
        </SafeAreaView>
      )}
    </View>
  );
}
