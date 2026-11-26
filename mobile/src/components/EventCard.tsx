import { Link } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { Photo } from "@/components/Photo";
import { Chip } from "@/components/ui";
import { eventImage } from "@/lib/images";
import { dayMonth, inr, timeOf } from "@/lib/format";
import type { EventListItem } from "@/lib/types";
import { color, font } from "@/theme";

export function EventCard({ e, wide }: { e: EventListItem; wide?: boolean }) {
  const past = new Date(e.starts_at).getTime() < Date.now();
  return (
    <Link href={{ pathname: "/event/[slug]", params: { slug: e.slug } }} asChild>
      <Pressable accessibilityRole="link" style={{ width: wide ? 280 : "100%", borderRadius: 24, overflow: "hidden", backgroundColor: color.surface, borderWidth: 1, borderColor: color.line }}>
        <Photo source={eventImage(e)} style={{ width: "100%", aspectRatio: 4 / 3 }} />
        <View style={{ padding: 16, gap: 6 }}>
          {e.is_sold_out ? <Chip label="Sold out" /> : past ? <Chip label="Past event" /> : null}
          <Text style={{ fontFamily: font.serif, fontSize: 22, lineHeight: 26, color: color.white }} numberOfLines={2}>{e.title}</Text>
          <Text style={{ fontFamily: font.sans, fontSize: 14, color: color.muted }}>{dayMonth(e.starts_at, e.timezone)} · {timeOf(e.starts_at, e.timezone)}</Text>
          <Text style={{ fontFamily: font.sans, fontSize: 14, color: color.faint }} numberOfLines={1}>{e.venue_name}, {e.city}</Text>
          {e.starting_price_paise != null && !past && !e.is_sold_out && (
            <Text style={{ fontFamily: font.sansBold, fontSize: 14, color: color.white, marginTop: 4 }}>From {inr(e.starting_price_paise)}</Text>
          )}
        </View>
      </Pressable>
    </Link>
  );
}
