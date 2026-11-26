import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Body, H1, Label, PillButton } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Booking, Ticket } from "@/lib/types";
import { color, font } from "@/theme";

export default function Confirmed() {
  const { reference, title, when, venue } = useLocalSearchParams<{ reference: string; title?: string; when?: string; venue?: string }>();
  const { user } = useAuth();
  const router = useRouter();
  const [b, setB] = useState<Booking | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => { Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {}); }, []);
  useEffect(() => { api<Booking>(`bookings/${reference}`).then(setB).catch(() => {}); }, [reference]);

  // Tickets are issued a moment after payment.
  useEffect(() => {
    let live = true;
    (async () => {
      for (let i = 0; i < 20 && live; i++) {
        try {
          const t = await api<Ticket[] | { items: Ticket[] }>(`bookings/${reference}/tickets`);
          if ((Array.isArray(t) ? t : t.items).length > 0) { if (live) setReady(true); return; }
        } catch {}
        await new Promise((r) => setTimeout(r, 2500));
      }
    })();
    return () => { live = false; };
  }, [reference]);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }}>
      <ScrollView contentContainerStyle={{ padding: 24, gap: 16, flexGrow: 1, justifyContent: "center" }}>
        <View style={{ width: 72, height: 72, borderRadius: 36, borderWidth: 1, borderColor: color.good, alignItems: "center", justifyContent: "center", backgroundColor: color.good + "1a" }}>
          <Ionicons name="checkmark" size={36} color={color.good} />
        </View>
        <H1>You're in.</H1>
        <Label>Booking {reference}</Label>

        <View style={{ padding: 18, borderRadius: 24, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line, gap: 6 }}>
          {!!title && <Text style={{ fontFamily: font.serif, fontSize: 22, color: color.white }}>{title}</Text>}
          {!!when && <Body style={{ fontSize: 14 }}>{when}</Body>}
          {!!venue && <Body style={{ fontSize: 14 }}>{venue}</Body>}
          {b && <Body style={{ fontSize: 14, color: color.text, marginTop: 6 }}>{b.quantity} {b.quantity === 1 ? "ticket" : "tickets"} confirmed</Body>}
        </View>

        <Body>{ready ? "Your tickets are ready." : "Getting your tickets ready…"}{user?.email ? ` A copy is on its way to ${user.email}.` : ""}</Body>
        <PillButton label="View tickets" onPress={() => router.replace("/tickets")} disabled={!ready} busy={!ready} />
        <PillButton label="Back to events" tone="ghost" arrow={false} onPress={() => router.replace("/")} />
      </ScrollView>
    </SafeAreaView>
  );
}
