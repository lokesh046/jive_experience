import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { Body, PillButton } from "@/components/ui";
import { openDirections } from "@/lib/deviceActions";
import { timeOf } from "@/lib/format";
import { addressOf } from "@/lib/maps";
import type { EventDay } from "@/lib/useEventDay";
import { color, font } from "@/theme";

function when(startMs: number, now: number): { kicker: string; line: string } {
  const mins = Math.round((startMs - now) / 60000);
  if (mins <= -1) return { kicker: "Happening now", line: "Started " + (-mins < 60 ? `${-mins} min ago` : `${Math.floor(-mins / 60)} h ago`) };
  if (mins < 1) return { kicker: "Starting now", line: "Starting now" };
  const h = Math.floor(mins / 60), m = mins % 60;
  return { kicker: "Tonight", line: `Starts in ${h ? `${h} h ` : ""}${m} min` };
}

/** On the night itself: the ticket and the way there, one tap away. */
export function EventDayBanner({ day }: { day: EventDay }) {
  const router = useRouter();
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 30_000); return () => clearInterval(t); }, []);
  const { event, booking, venue } = day;
  const start = new Date(event.starts_at).getTime();
  const w = when(start, now);
  const place = {
    name: venue?.name ?? event.venue_name,
    latitude: venue?.latitude, longitude: venue?.longitude,
    address: venue ? addressOf(venue) : `${event.venue_name}, ${event.city}`,
  };
  return (
    <View accessibilityRole="summary" style={{ marginHorizontal: 20, marginBottom: 20, padding: 20, borderRadius: 28, backgroundColor: color.surface, borderWidth: 1, borderColor: color.amber + "88", gap: 8 }}>
      <Text style={{ fontFamily: font.sansBold, fontSize: 12, letterSpacing: 1.6, textTransform: "uppercase", color: color.amber }}>{w.kicker}</Text>
      <Text style={{ fontFamily: font.serif, fontSize: 30, lineHeight: 33, color: color.white }}>{event.title}</Text>
      <Body style={{ color: color.text }}>{timeOf(event.starts_at, event.timezone)} · {w.line}</Body>
      <Body style={{ fontSize: 14 }}>{event.venue_name}, {event.city}</Body>
      <Body style={{ fontSize: 14 }}>{booking.quantity} {booking.quantity === 1 ? "ticket" : "tickets"}</Body>
      {day.offline && <Text style={{ fontFamily: font.sansMedium, fontSize: 12, color: color.amber }}>No signal. Your tickets are saved on this phone.</Text>}
      <PillButton label="Show my ticket" onPress={() => router.push({ pathname: "/ticket/[reference]", params: { reference: booking.reference } })} style={{ marginTop: 8 }} />
      <PillButton label="Directions" tone="ghost" arrow={false} onPress={() => openDirections(place)} />
    </View>
  );
}
