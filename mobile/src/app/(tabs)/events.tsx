import { FlatList, RefreshControl, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { EventCard } from "@/components/EventCard";
import { Body, H1 } from "@/components/ui";
import { useEvents } from "@/lib/useEvents";
import { color } from "@/theme";

export default function Events() {
  const { events, error, refreshing, refresh } = useEvents();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }} edges={["top"]}>
      <FlatList
        data={events ?? []}
        keyExtractor={(e) => e.id}
        renderItem={({ item }) => <EventCard e={item} />}
        ItemSeparatorComponent={() => <View style={{ height: 16 }} />}
        ListHeaderComponent={<View style={{ paddingBottom: 16, gap: 8 }}><H1>Events</H1></View>}
        ListEmptyComponent={<Body>{error ?? (events ? "No events on sale right now." : "Loading…")}</Body>}
        contentContainerStyle={{ padding: 20, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={color.white} />}
      />
    </SafeAreaView>
  );
}
