import { Ionicons } from "@expo/vector-icons";
import { Pressable, Text, View } from "react-native";
import { Body } from "@/components/ui";
import { HEADLINE, RESULT_TONE, readable } from "@/lib/scan";
import { timeOf } from "@/lib/format";
import type { ScanResponse } from "@/lib/types";
import { color, font } from "@/theme";

const TONE = { good: color.good, warn: color.warn, bad: color.bad, neutral: color.muted };

/** One sheet for all eight outcomes. Entry moves on by itself; every refusal waits for a tap. */
export function ScanResultSheet({ r, onDismiss }: { r: ScanResponse; onDismiss: () => void }) {
  const tone = TONE[RESULT_TONE[r.result]];
  const icon = r.ok ? "checkmark" : r.result === "ALREADY_USED" ? "alert" : "close";
  const rows: [string, string][] = [];
  if (r.ticket_category) rows.push(["Category", r.ticket_category]);
  if (r.ticket_serial) rows.push(["Ticket", r.ticket_serial]);
  if (r.attendee_name) rows.push(["Name", r.attendee_name]);
  if (r.checked_in_at) rows.push([r.ok ? "Scanned" : "First scanned", timeOf(r.checked_in_at)]);
  return (
    <Pressable onPress={onDismiss} accessibilityRole="button" accessibilityLiveRegion="assertive"
      style={{ position: "absolute", left: 0, right: 0, top: 0, bottom: 0, backgroundColor: tone + "f2", padding: 28, justifyContent: "center", gap: 14 }}>
      <View style={{ width: 84, height: 84, borderRadius: 42, backgroundColor: "#0a0a0a", alignItems: "center", justifyContent: "center" }}>
        <Ionicons name={icon} size={46} color={tone} />
      </View>
      <Text style={{ fontFamily: font.serif, fontSize: 44, lineHeight: 48, color: "#0a0a0a" }}>{HEADLINE[r.result] ?? r.result}</Text>
      <Body style={{ color: "#0a0a0a", fontSize: 17 }}>{readable(r.message)}</Body>
      {rows.length > 0 && (
        <View style={{ gap: 6, marginTop: 6 }}>
          {rows.map(([k, v]) => (
            <View key={k} style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={{ fontFamily: font.sansMedium, color: "#0a0a0a99", fontSize: 15 }}>{k}</Text>
              <Text style={{ fontFamily: font.sansBold, color: "#0a0a0a", fontSize: 15 }}>{v}</Text>
            </View>
          ))}
        </View>
      )}
      <View style={{ height: 56, borderRadius: 28, backgroundColor: "#0a0a0a", alignItems: "center", justifyContent: "center", marginTop: 12 }}>
        <Text style={{ fontFamily: font.sansBold, color: color.white, fontSize: 16 }}>{r.ok ? "Scan next" : "Dismiss"}</Text>
      </View>
    </Pressable>
  );
}
