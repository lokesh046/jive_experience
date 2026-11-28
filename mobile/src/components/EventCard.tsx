import { Ionicons } from "@expo/vector-icons";
import { Link } from "expo-router";
import { Pressable, Text, View } from "react-native";
import Animated, { Easing, interpolate, useAnimatedStyle, useReducedMotion, useSharedValue, withSpring, withTiming } from "react-native-reanimated";
import { Photo } from "@/components/Photo";
import { eventImage } from "@/lib/images";
import { inr, timeOf } from "@/lib/format";
import type { EventListItem } from "@/lib/types";
import { color, font } from "@/theme";

/** "Mon 21 Dec · 4:47 PM", in the event's own time zone. */
function when(e: EventListItem): string {
  const d = new Date(e.starts_at);
  const day = new Intl.DateTimeFormat("en-IN", { timeZone: e.timezone, weekday: "short", day: "numeric", month: "short" }).format(d).replace(",", "");
  return `${day} · ${timeOf(e.starts_at, e.timezone)}`;
}

export function EventCard({ e, wide }: { e: EventListItem; wide?: boolean }) {
  const past = new Date(e.starts_at).getTime() < Date.now();
  const status = e.is_sold_out ? "Sold out" : past ? "Past event" : null;
  const priced = e.starting_price_paise != null && !past && !e.is_sold_out;

  // One authored moment: touching the card sends the arrow forward. It springs back on release.
  const reduce = useReducedMotion();
  const press = useSharedValue(0);
  const card = useAnimatedStyle(() => ({ transform: [{ scale: interpolate(press.value, [0, 1], [1, 0.985]) }] }));
  const disc = useAnimatedStyle(() => ({ transform: [{ scale: interpolate(press.value, [0, 1], [1, 1.14]) }] }));
  const arrow = useAnimatedStyle(() => ({ transform: [{ translateX: interpolate(press.value, [0, 1], [0, 3]) }] }));

  return (
    <Link href={{ pathname: "/event/[slug]", params: { slug: e.slug } }} asChild>
      <Pressable
        accessibilityRole="link"
        accessibilityLabel={`${e.title}, ${when(e)}, ${e.venue_name}, ${e.city}${status ? `, ${status}` : priced ? `, from ${inr(e.starting_price_paise!)}` : ""}`}
        onPressIn={() => { press.value = reduce ? 1 : withTiming(1, { duration: 140, easing: Easing.out(Easing.exp) }); }}
        onPressOut={() => { press.value = reduce ? 0 : withSpring(0, { damping: 12, stiffness: 220 }); }}
        style={{ width: wide ? 280 : "100%" }}
      >
        <Animated.View style={[{ borderRadius: 24, overflow: "hidden", backgroundColor: color.surface, borderWidth: 1, borderColor: color.line }, card]}>
        <Photo source={eventImage(e)} style={{ width: "100%", aspectRatio: 4 / 3 }} />

        {/* One reading path: what it is, when and where, then the price and the way in. */}
        <View style={{ padding: 18, gap: 16 }}>
          <View style={{ gap: 10 }}>
            {/* Room for two lines, always, so every card in a row is the same height. */}
            <View style={{ minHeight: 56 }}>
              <Text style={{ fontFamily: font.serif, fontSize: 24, lineHeight: 28, color: color.white }} numberOfLines={2}>{e.title}</Text>
            </View>
            <View style={{ gap: 6 }}>
              <Meta icon="location-outline" text={`${e.venue_name}, ${e.city}`} />
              <Meta icon="calendar-outline" text={when(e)} strong />
            </View>
          </View>

          <View style={{ height: 1, backgroundColor: color.line }} />

          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 36 }}>
            {priced ? (
              <Text>
                <Text style={{ fontFamily: font.sans, fontSize: 13, color: color.muted }}>From </Text>
                <Text style={{ fontFamily: font.serif, fontSize: 22, color: color.white }}>{inr(e.starting_price_paise!)}</Text>
              </Text>
            ) : (
              <Text style={{ fontFamily: font.sansMedium, fontSize: 14, color: color.muted }}>{status ?? "Details"}</Text>
            )}
            <Animated.View style={[{ width: 36, height: 36, borderRadius: 18, backgroundColor: priced ? color.white : color.surfaceHigh, alignItems: "center", justifyContent: "center" }, disc]}>
              <Animated.View style={arrow}><Ionicons name="arrow-forward" size={18} color={priced ? color.ink : color.white} /></Animated.View>
            </Animated.View>
          </View>
        </View>
        </Animated.View>
      </Pressable>
    </Link>
  );
}

/** An icon and a line of text, on a shared grid so rows align down the card. */
function Meta({ icon, text, strong }: { icon: keyof typeof Ionicons.glyphMap; text: string; strong?: boolean }) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
      <View style={{ width: 18, alignItems: "center" }}><Ionicons name={icon} size={16} color={color.muted} /></View>
      <Text style={{ flex: 1, fontFamily: strong ? font.sansMedium : font.sans, fontSize: 14, lineHeight: 20, color: strong ? color.text : color.muted }} numberOfLines={1}>{text}</Text>
    </View>
  );
}
