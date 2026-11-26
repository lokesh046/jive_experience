import { Image } from "expo-image";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Body, Chip, H1 } from "@/components/ui";
import { api } from "@/lib/api";
import { eventsById } from "@/lib/eventsIndex";
import { dayMonth, inr } from "@/lib/format";
import { STATUS_LABEL, statusTone } from "@/lib/status";
import type { Booking, EventListItem, Page } from "@/lib/types";
import { color, font } from "@/theme";

export default function Tickets() {
  const router = useRouter();
  const [rows, setRows] = useState<Booking[] | null>(null);
  const [events, setEvents] = useState<Map<string, EventListItem>>(new Map());
  const [tab, setTab] = useState<"up" | "past">("up");
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (force = false) => {
    try {
      const [b, ev] = await Promise.all([api<Page<Booking>>("bookings?size=50"), eventsById(force)]);
      setRows(b.items); setEvents(ev); setError(null);
    } catch (e: any) { setError(e?.message ?? "We could not load your bookings."); }
  }, []);

  // Reload whenever the tab is shown, so a booking just paid for appears.
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const now = Date.now();
  const upcoming = (b: Booking) => {
    if (b.status === "CANCELLED" || b.status === "REFUNDED" || b.status === "EXPIRED") return false;
    const ev = events.get(b.event_id);
    return ev ? new Date(ev.starts_at).getTime() >= now : b.status === "CONFIRMED" || b.status === "PENDING";
  };
  const shown = (rows ?? []).filter((b) => (tab === "up" ? upcoming(b) : !upcoming(b)));

  function open(b: Booking) {
    if (b.status === "PENDING") router.push({ pathname: "/checkout/[reference]", params: { reference: b.reference, title: events.get(b.event_id)?.title } });
    else router.push({ pathname: "/ticket/[reference]", params: { reference: b.reference } });
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }} edges={["top"]}>
      <FlatList
        data={shown}
        keyExtractor={(b) => b.id}
        contentContainerStyle={{ padding: 20, paddingBottom: 40, gap: 16 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(true); setRefreshing(false); }} tintColor={color.white} />}
        ListHeaderComponent={
          <View style={{ gap: 16, marginBottom: 4 }}>
            <H1>My tickets</H1>
            <View accessibilityRole="tablist" style={{ flexDirection: "row", padding: 4, borderRadius: 999, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line }}>
              {(["up", "past"] as const).map((t) => (
                <Pressable key={t} accessibilityRole="tab" accessibilityState={{ selected: tab === t }} onPress={() => setTab(t)}
                  style={{ flex: 1, height: 40, borderRadius: 999, alignItems: "center", justifyContent: "center", backgroundColor: tab === t ? color.white : "transparent" }}>
                  <Text style={{ fontFamily: font.sansBold, color: tab === t ? color.ink : color.muted }}>{t === "up" ? "Upcoming" : "Past"}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        }
        ListEmptyComponent={<Body>{error ?? (rows === null ? "Loading…" : tab === "up" ? "Nothing booked yet. Find a night in Events." : "No past bookings.")}</Body>}
        renderItem={({ item: b }) => {
          const ev = events.get(b.event_id);
          const pending = b.status === "PENDING";
          return (
            <Pressable onPress={() => open(b)} accessibilityRole="button" style={{ borderRadius: 24, overflow: "hidden", backgroundColor: color.surface, borderWidth: 1, borderColor: color.line }}>
              {ev?.thumbnail_image_url && <Image source={ev.thumbnail_image_url} style={{ width: "100%", height: 130 }} contentFit="cover" />}
              <View style={{ padding: 16, gap: 6 }}>
                <Chip label={STATUS_LABEL[b.status] ?? b.status} tone={statusTone(b.status)} />
                <Text style={{ fontFamily: font.serif, fontSize: 22, color: color.white }}>{ev?.title ?? "Booking"}</Text>
                {ev && <Body style={{ fontSize: 14 }}>{dayMonth(ev.starts_at, ev.timezone)} · {ev.venue_name}, {ev.city}</Body>}
                <Body style={{ fontSize: 14, color: color.text }}>{b.items.map((i) => `${i.category_name} × ${i.quantity}`).join(", ")}</Body>
                <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 4 }}>
                  <Text style={{ fontFamily: font.sansBold, color: color.white }}>{inr(b.total_paise)}</Text>
                  <Text style={{ fontFamily: font.sansMedium, color: color.white }}>{pending ? "Complete payment →" : "View tickets →"}</Text>
                </View>
              </View>
            </Pressable>
          );
        }}
      />
    </SafeAreaView>
  );
}
