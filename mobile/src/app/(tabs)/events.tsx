import { Ionicons } from "@expo/vector-icons";
import { useMemo, useState } from "react";
import { FlatList, Pressable, RefreshControl, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { EventCard } from "@/components/EventCard";
import { Body, H1 } from "@/components/ui";
import { useDebounced } from "@/lib/useDebounced";
import { useEvents } from "@/lib/useEvents";
import type { EventListItem } from "@/lib/types";
import { color, font } from "@/theme";

const SEARCH_MAX = 60;       // longest search we accept
const SEARCH_WARN = 50;      // show the counter from here
const SEARCH_DELAY_MS = 250; // wait for a pause in typing before filtering

const fold = (t: string) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** What a search can match: the words people would use to look for a night. */
function haystack(e: EventListItem): string {
  const month = new Intl.DateTimeFormat("en-IN", { month: "long", timeZone: e.timezone }).format(new Date(e.starts_at));
  return fold([e.title, e.subtitle, e.venue_name, e.city, e.category.replace(/_/g, " "), month].filter(Boolean).join(" "));
}

export default function Events() {
  const up = useEvents(false);
  const past = useEvents(true);
  const [tab, setTab] = useState<"upcoming" | "past">("upcoming");
  const [city, setCity] = useState("all");
  const [query, setQuery] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const source = tab === "past" ? past : up;
  const events = source.events ?? [];
  const cities = useMemo(() => [...new Set(events.map((e) => e.city))].sort(), [events]);
  const index = useMemo(() => new Map(events.map((e) => [e.id, haystack(e)])), [events]);
  // The box answers every keystroke at once; the list waits for a pause. Clearing applies immediately.
  const settled = useDebounced(query, query ? SEARCH_DELAY_MS : 0);
  const words = fold(settled).split(/\s+/).filter(Boolean);
  const shown = events.filter((e) => city === "all" || e.city === city).filter((e) => words.every((w) => index.get(e.id)?.includes(w)));
  const searching = words.length > 0;
  const loaded = source.events !== null;

  const pill = (label: string, on: boolean, onPress: () => void) => (
    <Pressable key={label} onPress={onPress} accessibilityRole="button" accessibilityState={{ selected: on }}
      style={{ height: 38, paddingHorizontal: 16, borderRadius: 19, borderWidth: 1, borderColor: on ? color.white : color.line, backgroundColor: on ? color.white : "transparent", alignItems: "center", justifyContent: "center" }}>
      <Text style={{ fontFamily: font.sansMedium, fontSize: 14, color: on ? color.ink : color.white }}>{label}</Text>
    </Pressable>
  );

  const emptyText = source.error && !loaded ? source.error
    : !loaded ? "Loading…"
    : searching || city !== "all" ? `Nothing matches${searching ? ` “${settled.trim()}”` : ""}.`
    : tab === "past" ? "No past events yet." : "No upcoming nights yet. New dates are announced here first.";

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }} edges={["top"]}>
      <FlatList
        data={shown}
        keyExtractor={(e) => e.id}
        renderItem={({ item }) => <EventCard e={item} />}
        ItemSeparatorComponent={() => <View style={{ height: 16 }} />}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        contentContainerStyle={{ padding: 20, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await Promise.all([up.refresh(), past.refresh()]); setRefreshing(false); }} tintColor={color.white} />}
        ListHeaderComponent={
          <View style={{ gap: 14, paddingBottom: 18 }}>
            <H1>Events</H1>

            {(past.events?.length ?? 0) > 0 && (
              <View accessibilityRole="tablist" style={{ flexDirection: "row", padding: 4, borderRadius: 999, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line }}>
                {(["upcoming", "past"] as const).map((t) => (
                  <Pressable key={t} accessibilityRole="tab" accessibilityState={{ selected: tab === t }} onPress={() => { setTab(t); setCity("all"); }}
                    style={{ flex: 1, height: 40, borderRadius: 999, alignItems: "center", justifyContent: "center", backgroundColor: tab === t ? color.white : "transparent" }}>
                    <Text style={{ fontFamily: font.sansBold, color: tab === t ? color.ink : color.muted }}>
                      {t === "upcoming" ? `Upcoming${up.events?.length ? ` (${up.events.length})` : ""}` : `Past (${past.events?.length ?? 0})`}
                    </Text>
                  </Pressable>
                ))}
              </View>
            )}

            <View accessibilityRole="search" style={{ height: 52, borderRadius: 26, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line, flexDirection: "row", alignItems: "center", paddingLeft: 18, paddingRight: 8, gap: 10 }}>
              <Ionicons name="search" size={20} color={color.muted} />
              <TextInput
                value={query}
                onChangeText={(t) => setQuery(t.replace(/\s+/g, " ").slice(0, SEARCH_MAX))}
                placeholder="Search by event, venue, city or month"
                placeholderTextColor={color.faint}
                accessibilityLabel="Search events"
                returnKeyType="search"
                autoCorrect={false}
                autoCapitalize="none"
                maxLength={SEARCH_MAX}
                style={{ flex: 1, height: 52, color: color.white, fontFamily: font.sans, fontSize: 16 }}
              />
              {query.length >= SEARCH_WARN && (
                <Text accessibilityLabel={`${query.length} of ${SEARCH_MAX} characters`} style={{ fontFamily: font.sans, fontSize: 12, color: query.length >= SEARCH_MAX ? color.warn : color.faint }}>{query.length}/{SEARCH_MAX}</Text>
              )}
              {!!query && (
                <Pressable onPress={() => setQuery("")} accessibilityRole="button" accessibilityLabel="Clear search" hitSlop={8} style={{ width: 36, height: 36, alignItems: "center", justifyContent: "center" }}>
                  <Ionicons name="close-circle" size={20} color={color.muted} />
                </Pressable>
              )}
            </View>

            {cities.length > 1 && (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }} accessibilityLabel="Filter by city">
                {["all", ...cities].map((c) => pill(c === "all" ? "All cities" : c, city === c, () => setCity(c)))}
              </ScrollView>
            )}

            {(searching || settled !== query) && <Text accessibilityLiveRegion="polite" style={{ fontFamily: font.sans, fontSize: 13, color: color.muted }}>{settled !== query ? "Searching…" : `${shown.length} ${shown.length === 1 ? "event" : "events"} found`}</Text>}
          </View>
        }
        ListEmptyComponent={
          <View style={{ gap: 12 }}>
            <Body>{emptyText}</Body>
            {loaded && (searching || city !== "all") && (
              <Pressable onPress={() => { setQuery(""); setCity("all"); }} accessibilityRole="button"><Text style={{ fontFamily: font.sansMedium, color: color.white, textDecorationLine: "underline" }}>Show all events</Text></Pressable>
            )}
          </View>
        }
      />
    </SafeAreaView>
  );
}
