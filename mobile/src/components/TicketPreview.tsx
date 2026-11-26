import { LinearGradient } from "expo-linear-gradient";
import { Platform, Text, View } from "react-native";
import { color, font } from "@/theme";

const MONO = Platform.select({ ios: "Menlo", default: "monospace" });
const NOTCH = color.bg;

/**
 * A ticket that fills in as the customer chooses, as on the website. It is a preview: the real
 * ticket and its QR code are issued after payment.
 */
export function TicketPreview({ when, title, venue, ticket, admit, total, premium = false, year }: {
  when: string; title: string; venue: string; ticket: string | null; admit: number; total: string | null; premium?: boolean; year?: string;
}) {
  return premium ? <Premium {...{ when, title, venue, ticket, admit, total, year }} /> : <Cream {...{ when, title, venue, ticket, admit, total }} />;
}

const Kick = ({ children, ink }: { children: React.ReactNode; ink: string }) => (
  <Text style={{ fontFamily: MONO, fontSize: 11, letterSpacing: 1.6, textTransform: "uppercase", color: ink }}>{children}</Text>
);

function Cream({ when, title, venue, ticket, admit, total }: { when: string; title: string; venue: string; ticket: string | null; admit: number; total: string | null }) {
  const ink = "#241b30", soft = "#6d6272", faint = "#a89f8f";
  const field = (label: string, value: string | null, empty: string) => (
    <View style={{ gap: 4 }}>
      <Kick ink={soft}>{label}</Kick>
      <Text style={{ fontFamily: MONO, fontWeight: value ? "700" : "400", fontSize: 18, color: value ? ink : faint }}>{value ?? empty}</Text>
    </View>
  );
  return (
    <View accessible accessibilityLabel="Ticket preview" style={{ borderRadius: 22, overflow: "hidden", backgroundColor: "#efe7d8" }}>
      <LinearGradient colors={["#f4eee2", "#d9cfbd"]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ position: "absolute", left: 0, right: 0, top: 0, bottom: 0 }} />
      <View style={{ padding: 22, paddingBottom: 24, gap: 8 }}>
        <Kick ink={soft}>{when}</Kick>
        <Text style={{ fontFamily: font.serif, fontSize: 28, lineHeight: 30, color: ink, marginTop: 4 }}>{title}</Text>
        <Text style={{ fontFamily: font.sans, fontSize: 14, color: soft }}>{venue}</Text>
        <View style={{ flexDirection: "row", gap: 28, flexWrap: "wrap", marginTop: 14, paddingTop: 16, borderTopWidth: 1, borderStyle: "dashed", borderColor: faint }}>
          {field("Ticket", ticket, "Choose below")}
          {field("Admit", admit ? String(admit) : null, "—")}
          {field("Total", total, "—")}
        </View>
      </View>
      <View style={{ borderTopWidth: 2, borderStyle: "dotted", borderColor: "#1a1420", paddingHorizontal: 22, paddingVertical: 16, flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <Kick ink={soft}>{admit > 1 ? `Admit ${admit}` : "Admit one"}</Kick>
        <Bars ink={ink} />
        <Text style={{ fontFamily: MONO, fontSize: 10, letterSpacing: 1.2, textTransform: "uppercase", color: soft, textAlign: "right", maxWidth: 90 }}>JIVE · after payment</Text>
      </View>
      <View style={{ position: "absolute", left: -13, bottom: 66 - 13, width: 26, height: 26, borderRadius: 13, backgroundColor: NOTCH }} />
      <View style={{ position: "absolute", right: -13, bottom: 66 - 13, width: 26, height: 26, borderRadius: 13, backgroundColor: NOTCH }} />
    </View>
  );
}

function Bars({ ink }: { ink: string }) {
  const widths = [3, 3, 1, 4, 3, 1, 3, 4, 1, 3];
  return (
    <View style={{ flexDirection: "row", gap: 3, height: 34, alignItems: "stretch" }}>
      {widths.map((w, i) => <View key={i} style={{ width: w, backgroundColor: ink }} />)}
    </View>
  );
}

function Premium({ when, title, venue, ticket, admit, total, year }: { when: string; title: string; venue: string; ticket: string | null; admit: number; total: string | null; year?: string }) {
  const ink = "#5a3520";
  const caps = { fontFamily: font.sansMedium, textTransform: "uppercase" as const, color: ink, letterSpacing: 0.4 };
  return (
    <View accessible accessibilityLabel="Ticket preview" style={{ borderRadius: 26, overflow: "hidden", backgroundColor: "#e5702f" }}>
      <LinearGradient colors={["#ef8a4c", "#e5702f", "#e5702f", "#f6cc9c"]} locations={[0, 0.35, 0.7, 1]} start={{ x: 0.8, y: 0 }} end={{ x: 0.2, y: 1 }} style={{ position: "absolute", left: 0, right: 0, top: 0, bottom: 0 }} />
      <View style={{ padding: 24, paddingBottom: 22, minHeight: 250 }}>
        <Text style={[caps, { fontSize: 15, lineHeight: 20 }]}>JIVE presents · {title}</Text>
        <Text style={[caps, { fontSize: 14, marginTop: 2 }]}>{when}</Text>
        <Text adjustsFontSizeToFit numberOfLines={2} style={{ fontFamily: font.sansMedium, fontSize: 64, lineHeight: 64, letterSpacing: -1.5, textTransform: "uppercase", color: ink, marginTop: 28 }}>{ticket ?? "VIP"}</Text>
        <Text style={[caps, { fontSize: 14, marginTop: 18 }]}>{venue}</Text>
        <View style={{ flexDirection: "row", gap: 28, marginTop: 14 }}>
          <View><Text style={[caps, { fontSize: 11, opacity: 0.7 }]}>Admit</Text><Text style={{ fontFamily: MONO, fontWeight: "700", fontSize: 18, color: ink }}>{admit || "—"}</Text></View>
          <View><Text style={[caps, { fontSize: 11, opacity: 0.7 }]}>Total</Text><Text style={{ fontFamily: MONO, fontWeight: "700", fontSize: 18, color: ink }}>{total ?? "—"}</Text></View>
        </View>
      </View>
      <View style={{ height: 96, borderTopWidth: 2, borderStyle: "dashed", borderColor: "rgba(90,53,32,0.45)", alignItems: "center", justifyContent: "center", overflow: "hidden" }}>
        {!!year && <Text style={{ position: "absolute", fontFamily: font.sansBold, fontSize: 88, color: "rgba(255,236,214,0.4)", letterSpacing: -3 }}>{year}</Text>}
        <Text style={[caps, { fontSize: 24, letterSpacing: 0 }]}>{admit > 1 ? `Admit ${admit}` : "Admit one"}</Text>
      </View>
      {/* The tear-line notches sit where the stub starts. */}
      <View style={{ position: "absolute", left: -22, bottom: 96 - 22, width: 44, height: 44, borderRadius: 22, backgroundColor: NOTCH }} />
      <View style={{ position: "absolute", right: -22, bottom: 96 - 22, width: 44, height: 44, borderRadius: 22, backgroundColor: NOTCH }} />
    </View>
  );
}
