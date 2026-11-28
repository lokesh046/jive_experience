import type React from "react";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import * as Linking from "expo-linking";
import { useEffect, useRef, useState } from "react";
import { ScrollView, Text, useWindowDimensions, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { WebView } from "react-native-webview";
import { WaitlistForm } from "@/components/Forms";
import { Photo } from "@/components/Photo";
import { LoopCarousel } from "@/components/LoopCarousel";
import { TicketPicker, usePicker } from "@/components/TicketPicker";
import { TicketPreview } from "@/components/TicketPreview";
import { Body, Chip, ErrorLine, H1, H2, Label, PillButton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { BOOKING_MESSAGES, idempotencyKey } from "@/lib/booking";
import { addToCalendar, openDirections } from "@/lib/deviceActions";
import { dayMonth, inr, longDate, timeOf } from "@/lib/format";
import { addressOf, embedUrl, isWebLink, mapQuery, searchUrl } from "@/lib/maps";
import { describePolicy } from "@/lib/policy";
import { isPremiumType } from "@/lib/premium";
import { SITE_URL } from "@/lib/config";
import { eventImage, site } from "@/lib/images";
import type { Booking, EventDetail } from "@/lib/types";
import { color, font } from "@/theme";

export default function EventScreen() {
  const { slug, section } = useLocalSearchParams<{ slug: string; section?: string }>();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const scroll = useRef<React.ComponentRef<typeof ScrollView>>(null);
  const [ticketsY, setTicketsY] = useState(0);
  const [bodyY, setBodyY] = useState(0);
  const [photoAt, setPhotoAt] = useState(0);
  const [e, setE] = useState<EventDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const p = usePicker(e);
  const [busy, setBusy] = useState(false);
  const [bookError, setBookError] = useState<string | null>(null);
  const cancelled = e?.status === "CANCELLED";
  const sellable = !!e && e.on_sale && !e.is_past && !cancelled;

  // Arriving from a "Get tickets" button: land on the tickets once the page has been laid out.
  const jumped = useRef(false);
  useEffect(() => {
    if (section !== "tickets" || jumped.current || !e || !ticketsY) return;
    jumped.current = true;
    scroll.current?.scrollTo({ y: Math.max(0, bodyY + ticketsY - 12), animated: false });
  }, [section, e, ticketsY, bodyY]);

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

  const v = e?.venue;
  const prices = e ? e.ticket_categories.filter((c) => !c.is_sold_out).map((c) => c.price_paise) : [];
  const photos = e ? [...new Set([e.banner_image_url, ...e.gallery_image_urls].filter((u): u is string => !!u))] : [];
  if (e && photos.length === 0) photos.push(eventImage(e, "banner") || site("hero"));
  const refundLines = describePolicy(e?.cancellation_policy);
  const link = v ? [e?.location_url, v.map_url].find(isWebLink) ?? null : null;
  const query = v ? mapQuery(v, link) : "";
  const closed = e?.is_past ? "This night has passed. Tickets are no longer on sale."
    : cancelled ? "This event has been cancelled."
    : e?.is_sold_out ? "This event is sold out."
    : e?.sale_starts_at && new Date(e.sale_starts_at) > new Date() ? `Tickets go on sale ${longDate(e.sale_starts_at, e.timezone)}, ${timeOf(e.sale_starts_at, e.timezone)}.`
    : "Ticket sales have closed.";
  const H = (t: string) => <H2 style={{ marginTop: 36 }}>{t}</H2>;

  return (
    <View style={{ flex: 1, backgroundColor: color.bg }}>
      <Stack.Screen options={{ headerShown: true, headerTransparent: true, headerTitle: "", headerTintColor: color.white, headerBackButtonDisplayMode: "minimal" }} />
      <ScrollView ref={scroll} style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 56 }} keyboardShouldPersistTaps="handled">
        {error && <Body style={{ padding: 20, paddingTop: 100 }}>{error}</Body>}
        {e && v && (
          <>
            {/* Photos: swipe through the banner and gallery, round and round. */}
            <LoopCarousel
              data={photos}
              itemWidth={width}
              keyOf={(u) => u}
              onIndexChange={setPhotoAt}
              autoPlayMs={4000}
              renderItem={(u) => <Photo source={u} style={{ width, height: 340 }} />}
            />
            {photos.length > 1 && (
              <View accessibilityLabel={`Photo ${photoAt + 1} of ${photos.length}`} style={{ flexDirection: "row", gap: 6, justifyContent: "center", marginTop: 12 }}>
                {photos.map((u, i) => <View key={u} style={{ width: i === photoAt ? 20 : 6, height: 6, borderRadius: 3, backgroundColor: i === photoAt ? color.white : color.line }} />)}
              </View>
            )}

            <View onLayout={(ev) => setBodyY(ev.nativeEvent.layout.y)} style={{ padding: 20, gap: 10 }}>
              {e.is_past && !cancelled && <Chip label="Past event" />}
              {cancelled && <Chip label="Cancelled" tone="bad" />}
              <H1>{e.title}</H1>
              {!!e.subtitle && <Body>{e.subtitle}</Body>}
              <Body style={{ color: color.text }}>{longDate(e.starts_at, e.timezone)}, {timeOf(e.starts_at, e.timezone)}</Body>
              <Body>{v.name}, {v.city}</Body>

              <View style={{ gap: 10, marginTop: 8 }}>
                <PillButton
                  label={e.is_past ? "See upcoming events" : e.on_sale ? "Get tickets" : "See details"}
                  onPress={() => (e.is_past ? router.replace("/events") : scroll.current?.scrollTo({ y: Math.max(0, bodyY + ticketsY - 12), animated: true }))}
                />
                {!e.is_past && (
                  <PillButton label="Add to calendar" tone="ghost" arrow={false}
                    onPress={() => addToCalendar({ title: e.title, subtitle: e.subtitle, starts_at: e.starts_at, ends_at: e.ends_at, where: addressOf(v), url: `${SITE_URL}/events/${e.slug}` })} />
                )}
              </View>

              {!!e.description && (
                <View style={{ gap: 10 }}>
                  {H("The night")}
                  {e.description.split(/\n{2,}/).map((t, i) => <Body key={i}>{t.trim()}</Body>)}
                </View>
              )}

              <View onLayout={(ev) => setTicketsY(ev.nativeEvent.layout.y)} style={{ gap: 10 }}>
                {H("Tickets")}
                {sellable && prices.length > 0 && <Body>From {inr(Math.min(...prices))}</Body>}
                {sellable && (
                  <View style={{ marginVertical: 8 }}>
                    <TicketPreview
                      when={`${longDate(e.starts_at, e.timezone)} · ${timeOf(e.starts_at, e.timezone)}`}
                      title={e.title}
                      venue={`${v.name}, ${v.city}`}
                      ticket={p.cat?.name ?? null}
                      premium={!!p.cat && isPremiumType(p.cat.name, p.cat.price_paise, e.ticket_categories.map((c) => c.price_paise))}
                      year={String(new Date(e.starts_at).getFullYear())}
                      admit={p.cat ? p.count : 0}
                      total={p.cat ? inr(p.total) : null}
                    />
                  </View>
                )}
                {sellable ? <TicketPicker e={e} p={p} /> : <Body>{closed}</Body>}
                {!e.on_sale && e.is_sold_out && !e.is_past && !cancelled && (
                  <View style={{ marginTop: 12 }}><WaitlistForm slug={e.slug} categories={e.ticket_categories.map((c) => ({ id: c.id, name: c.name }))} /></View>
                )}
              </View>

              {e.lineup.length > 0 && (
                <View style={{ gap: 14 }}>
                  {H("Lineup")}
                  {e.lineup.map((l, i) => (
                    <View key={`${l.name}-${i}`} style={{ flexDirection: "row", gap: 14, alignItems: "center" }}>
                      {l.photo_url
                        ? <Photo source={l.photo_url} style={{ width: 72, height: 72, borderRadius: 36 }} />
                        : <View style={{ width: 72, height: 72, borderRadius: 36, backgroundColor: color.surfaceHigh, alignItems: "center", justifyContent: "center" }}><Text style={{ fontFamily: font.serif, fontSize: 28, color: color.white }}>{l.name.charAt(0).toUpperCase()}</Text></View>}
                      <View style={{ flex: 1, gap: 2 }}>
                        {!!l.performs_at && <Label>{dayMonth(l.performs_at, e.timezone) === dayMonth(e.starts_at, e.timezone) ? timeOf(l.performs_at, e.timezone) : `${dayMonth(l.performs_at, e.timezone)} · ${timeOf(l.performs_at, e.timezone)}`}</Label>}
                        <Text style={{ fontFamily: font.serif, fontSize: 22, color: color.white }}>{l.name}</Text>
                        {!!l.role && <Body style={{ fontSize: 14 }}>{l.role}</Body>}
                      </View>
                    </View>
                  ))}
                </View>
              )}

              <View style={{ gap: 10 }}>
                {H("The venue")}
                <Body><Text style={{ color: color.white, fontFamily: font.sansMedium }}>{v.name}</Text>, {v.city}{v.state ? `, ${v.state}` : ""}.</Body>
                {(v.description ?? "").split(/\n{2,}/).map((t) => t.trim()).filter(Boolean).map((t, i) => <Body key={i}>{t}</Body>)}
                {!!v.directions && <Body>{v.directions}</Body>}
                {(v.image_urls ?? []).length > 0 && (
                  <View style={{ marginTop: 6 }}>
                    <LoopCarousel
                      data={v.image_urls ?? []}
                      itemWidth={260}
                      gap={12}
                      autoPlayMs={5000}
                      keyOf={(u) => u}
                      renderItem={(u) => <Photo source={u} style={{ width: 260, height: 180, borderRadius: 18, marginRight: 12 }} />}
                    />
                  </View>
                )}
                {(v.benefits ?? []).length > 0 && (
                  <View style={{ gap: 8, marginTop: 8 }}>
                    <Label>What the venue offers</Label>
                    {v.benefits!.map((b, i) => <Body key={i} style={{ color: color.text }}>•  {b}</Body>)}
                  </View>
                )}
              </View>

              <View style={{ gap: 12 }}>
                {H("Location")}
                <View style={{ height: 220, borderRadius: 20, overflow: "hidden", borderWidth: 1, borderColor: color.line }}>
                  <WebView source={{ uri: embedUrl(query) }} originWhitelist={["https://*"]} scrollEnabled={false} style={{ flex: 1, backgroundColor: color.surface }} accessibilityLabel={`Map showing ${addressOf(v)}`} />
                </View>
                <View style={{ gap: 2 }}>
                  <Text style={{ fontFamily: font.sansBold, color: color.white }}>{v.name}</Text>
                  {!!(v.address_line1 || v.address_line2) && <Body style={{ fontSize: 14 }}>{[v.address_line1, v.address_line2].filter(Boolean).join(", ")}</Body>}
                  <Body style={{ fontSize: 14 }}>{[v.city, v.state, v.postal_code].filter(Boolean).join(", ")}</Body>
                </View>
                <PillButton label="Get directions" tone="ghost" onPress={() => openDirections({ name: v.name, latitude: v.latitude, longitude: v.longitude, address: addressOf(v) })} />
              </View>

              <View style={{ gap: 10 }}>
                {H("Good to know")}
                <Label>Cancellations and refunds</Label>
                {refundLines.length > 0
                  ? refundLines.map((t, i) => <Body key={i} style={{ color: color.text }}>•  {t}</Body>)
                  : <Body>This event has no online cancellation. If your plans change, contact us and we will help.</Body>}
                <Text onPress={() => Linking.openURL(`${SITE_URL}/cancellation-policy`).catch(() => {})} style={{ fontFamily: font.sansMedium, color: color.white, textDecorationLine: "underline" }}>Read the full policy</Text>
                {!!e.terms_and_conditions && (
                  <View style={{ gap: 8, marginTop: 10 }}>
                    <Label>Terms for this event</Label>
                    {e.terms_and_conditions.split(/\r?\n/).map((t) => t.trim()).filter(Boolean).map((t, i) => <Body key={i} style={{ color: color.text }}>•  {t}</Body>)}
                  </View>
                )}
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
