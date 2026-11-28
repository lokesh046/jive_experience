import { Ionicons } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { FlatList, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { EventCard } from "@/components/EventCard";
import { EnquiryForm, NewsletterSignup } from "@/components/Forms";
import { EventDayBanner } from "@/components/EventDayBanner";
import { Photo } from "@/components/Photo";
import { Body, H1, H2, PillButton } from "@/components/ui";
import { PRIVATE_SERVICES } from "@/lib/content";
import { dayMonth, inr, timeOf } from "@/lib/format";
import { eventImage } from "@/lib/images";
import { useEventDay } from "@/lib/useEventDay";
import { useEvents } from "@/lib/useEvents";
import { useHomeExtras } from "@/lib/useHome";
import { useUnread } from "@/lib/useUnread";
import { color, font } from "@/theme";

const Section = ({ title, action, children }: { title: string; action?: { label: string; onPress: () => void }; children: React.ReactNode }) => (
  <View style={{ marginTop: 32, gap: 16 }}>
    <View style={{ paddingHorizontal: 20, flexDirection: "row", justifyContent: "space-between", alignItems: "flex-end" }}>
      <H2>{title}</H2>
      {action && <Pressable onPress={action.onPress} accessibilityRole="link" hitSlop={8}><Text style={{ fontFamily: font.sansMedium, color: color.white, textDecorationLine: "underline" }}>{action.label}</Text></Pressable>}
    </View>
    {children}
  </View>
);

export default function Home() {
  const { events, error, refreshing, refresh } = useEvents();
  const { artists, archive } = useHomeExtras(events);
  const router = useRouter();
  const unread = useUnread();
  const top = useSafeAreaInsets().top;
  const day = useEventDay();
  const hero = events?.find((e) => e.is_featured) ?? events?.[0];
  const go = (slug: string) => router.push({ pathname: "/event/[slug]", params: { slug } });

  return (
    <View style={{ flex: 1, backgroundColor: color.bg }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 48 }} keyboardShouldPersistTaps="handled" refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={color.white} />}>
        <View style={{ height: 60 + top, paddingHorizontal: 20, paddingTop: top + 8, marginBottom: day ? 8 : 0, flexDirection: "row", justifyContent: "space-between", alignItems: "center", zIndex: 2 }}>
          <Text style={{ fontFamily: font.serif, fontSize: 30, color: color.white, letterSpacing: 6 }}>jive</Text>
          <Pressable onPress={() => router.push("/notifications")} accessibilityRole="button" accessibilityLabel={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"} hitSlop={10}>
            <Ionicons name="notifications-outline" size={26} color={color.white} />
            {unread > 0 && <View style={{ position: "absolute", top: -2, right: -2, width: 10, height: 10, borderRadius: 5, backgroundColor: color.amber }} />}
          </Pressable>
        </View>

        {day && <EventDayBanner day={day} />}

        {error && !events && <Body style={{ paddingHorizontal: 20 }}>{error} Pull down to try again.</Body>}
        {!events && !error && <View style={{ marginHorizontal: 20, height: 420, borderRadius: 28, backgroundColor: color.surface }} />}

        {/* The banner: the soonest night, or the one an admin marked for the homepage. */}
        {events && !hero && (
          <View style={{ paddingHorizontal: 20, gap: 8 }}>
            <H1>Live music evenings</H1>
            <Body>Intimate nights in converted mills, vaults and warehouses. New dates are announced here first.</Body>
          </View>
        )}
        {hero && (
          <View style={{ height: 620 + (day ? 0 : top), marginTop: day ? 0 : -(60 + top), justifyContent: "flex-end", overflow: "hidden", backgroundColor: color.surface }}>
            <Photo source={eventImage(hero, "banner")} style={{ position: "absolute", left: 0, right: 0, top: 0, bottom: 0 }} transition={250} />
            {/* The website's banner fade: the photo shows through, darker towards the bottom. */}
            <LinearGradient pointerEvents="none" colors={["rgba(0,0,0,0.6)", "rgba(0,0,0,0.12)", "rgba(0,0,0,0.5)", "rgba(10,10,10,0.9)", "#0a0a0a"]} locations={[0, 0.16, 0.5, 0.8, 1]} style={{ position: "absolute", left: 0, right: 0, top: 0, bottom: 0 }} />
            <View style={{ padding: 20, paddingBottom: 20, gap: 8 }}>
              <H1 style={{ fontSize: 40, lineHeight: 42 }}>{hero.title}</H1>
              {!!hero.subtitle && <Body numberOfLines={2}>{hero.subtitle}</Body>}
              <Body style={{ color: color.text }}>{dayMonth(hero.starts_at, hero.timezone)} · {timeOf(hero.starts_at, hero.timezone)}</Body>
              <Body numberOfLines={1}>{hero.venue_name}, {hero.city}</Body>
              <PillButton label={hero.starting_price_paise ? `Get tickets · from ${inr(hero.starting_price_paise)}` : "Get tickets"} onPress={() => router.push({ pathname: "/event/[slug]", params: { slug: hero.slug, section: "tickets" } })} style={{ marginTop: 8 }} />
              {events && events.length > 1 && <PillButton label="See all nights" tone="ghost" arrow={false} onPress={() => router.push("/events")} />}
            </View>
          </View>
        )}

        {events && events.length > 0 && (
          <Section title="Upcoming nights" action={{ label: "See all events", onPress: () => router.push("/events") }}>
            <FlatList horizontal data={events.slice(0, 4)} keyExtractor={(e) => e.id} renderItem={({ item }) => <EventCard e={item} wide />} contentContainerStyle={{ paddingHorizontal: 20, gap: 14 }} showsHorizontalScrollIndicator={false} />
          </Section>
        )}

        <Section title="Artists">
          <FlatList horizontal data={artists} keyExtractor={(a) => a.name} showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 20, gap: 14 }}
            renderItem={({ item: a }) => (
              <View style={{ width: 170, gap: 6 }}>
                <Photo source={a.img} style={{ width: 170, height: 210, borderRadius: 20 }} />
                <Text style={{ fontFamily: font.serif, fontSize: 20, color: color.white }}>{a.name}</Text>
                {!!a.note && <Body style={{ fontSize: 13, lineHeight: 18 }} numberOfLines={3}>{a.note}</Body>}
              </View>
            )} />
        </Section>

        <Section title="From the archive">
          <FlatList horizontal data={archive} keyExtractor={(a, i) => a.img + i} showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 20, gap: 14 }}
            renderItem={({ item: a }) => (
              <View style={{ width: 260, gap: 8 }}>
                <Photo source={a.img} style={{ width: 260, height: 190, borderRadius: 20 }} />
                {!!a.caption && <Body style={{ fontSize: 13 }}>{a.caption}</Body>}
              </View>
            )} />
        </Section>

        <View style={{ marginTop: 48, paddingHorizontal: 20, gap: 16 }}>
          <H2>Private bookings</H2>
          <Body>Our rooms are available for private listening sessions, brand showcases and table reservations.</Body>
          <View style={{ gap: 14, marginTop: 8 }}>
            {PRIVATE_SERVICES.map((s) => (
              <View key={s.name} style={{ padding: 24, borderRadius: 24, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line, gap: 12 }}>
                <Text style={{ fontFamily: font.serif, fontSize: 24, lineHeight: 29, color: color.white }}>{s.name}</Text>
                <Body style={{ fontSize: 15, lineHeight: 24 }}>{s.note}</Body>
              </View>
            ))}
          </View>
          <View style={{ marginTop: 16 }}><EnquiryForm /></View>
        </View>

        <View style={{ marginTop: 48, paddingHorizontal: 20 }}><NewsletterSignup /></View>
      </ScrollView>
    </View>
  );
}
