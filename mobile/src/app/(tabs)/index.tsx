import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { FlatList, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { EventCard } from "@/components/EventCard";
import { Body, H1, H2, Label, PillButton } from "@/components/ui";
import { dayMonth, timeOf } from "@/lib/format";
import { useEvents } from "@/lib/useEvents";
import { useUnread } from "@/lib/useUnread";
import { color, font } from "@/theme";

export default function Home() {
  const { events, error, refreshing, refresh } = useEvents();
  const router = useRouter();
  const unread = useUnread();
  const hero = events?.find((e) => e.is_featured && !e.is_sold_out) ?? events?.[0];
  const rest = events?.filter((e) => e.id !== hero?.id) ?? [];

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }} edges={["top"]}>
      <ScrollView contentContainerStyle={{ paddingBottom: 32 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={color.white} />}>
        <View style={{ paddingHorizontal: 20, paddingTop: 8, paddingBottom: 16, flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <Text style={{ fontFamily: font.serif, fontSize: 30, color: color.white, letterSpacing: 6 }}>jive</Text>
          <Pressable onPress={() => router.push("/notifications")} accessibilityRole="button" accessibilityLabel={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"} hitSlop={10}>
            <Ionicons name="notifications-outline" size={26} color={color.white} />
            {unread > 0 && <View style={{ position: "absolute", top: -2, right: -2, width: 10, height: 10, borderRadius: 5, backgroundColor: color.amber }} />}
          </Pressable>
        </View>

        {error && !events && <Body style={{ paddingHorizontal: 20 }}>{error} Pull down to try again.</Body>}
        {!events && !error && <View style={{ marginHorizontal: 20, height: 360, borderRadius: 28, backgroundColor: color.surface }} />}

        {hero && (
          <View style={{ marginHorizontal: 20, borderRadius: 28, overflow: "hidden", backgroundColor: color.surface }}>
            <Image source={hero.banner_image_url ?? hero.thumbnail_image_url} style={{ width: "100%", height: 420 }} contentFit="cover" transition={200} />
            <View style={{ position: "absolute", left: 0, right: 0, bottom: 0, padding: 20, gap: 10, backgroundColor: "rgba(10,10,10,0.62)" }}>
              <H1 style={{ fontSize: 32, lineHeight: 36 }}>{hero.title}</H1>
              <Body style={{ color: color.text }}>{dayMonth(hero.starts_at, hero.timezone)} · {timeOf(hero.starts_at, hero.timezone)}</Body>
              <Body numberOfLines={1}>{hero.venue_name}, {hero.city}</Body>
              <PillButton label="Get tickets" onPress={() => router.push({ pathname: "/event/[slug]", params: { slug: hero.slug } })} style={{ marginTop: 6 }} />
            </View>
          </View>
        )}

        {rest.length > 0 && (
          <View style={{ marginTop: 32, gap: 12 }}>
            <View style={{ paddingHorizontal: 20, gap: 4 }}>
              <Label>Coming up</Label>
              <H2>Upcoming nights</H2>
            </View>
            <FlatList
              horizontal
              data={rest}
              keyExtractor={(e) => e.id}
              renderItem={({ item }) => <EventCard e={item} wide />}
              contentContainerStyle={{ paddingHorizontal: 20, gap: 14 }}
              showsHorizontalScrollIndicator={false}
            />
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
