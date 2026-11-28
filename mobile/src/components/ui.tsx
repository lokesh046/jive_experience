import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { ActivityIndicator, Pressable, Text as RNText, View, type StyleProp, type TextProps, type TextStyle, type ViewStyle } from "react-native";
import { color, font } from "@/theme";

export function H1({ style, ...p }: TextProps) {
  return <RNText {...p} style={[{ fontFamily: font.serif, fontSize: 38, lineHeight: 42, color: color.white }, style]} />;
}
export function H2({ style, ...p }: TextProps) {
  return <RNText {...p} style={[{ fontFamily: font.serif, fontSize: 26, lineHeight: 30, color: color.white }, style]} />;
}
export function Body({ style, ...p }: TextProps) {
  return <RNText {...p} style={[{ fontFamily: font.sans, fontSize: 16, lineHeight: 23, color: color.muted }, style]} />;
}
export function Label({ style, ...p }: TextProps) {
  return <RNText {...p} style={[{ fontFamily: font.sansMedium, fontSize: 11, letterSpacing: 1.6, textTransform: "uppercase", color: color.faint }, style]} />;
}

/** White pill with the dark arrow disc, as on the website. */
export function PillButton({ label, onPress, busy, disabled, arrow = true, tone = "solid", style }: {
  label: string; onPress: () => void; busy?: boolean; disabled?: boolean; arrow?: boolean; tone?: "solid" | "ghost"; style?: StyleProp<ViewStyle>;
}) {
  const off = disabled || busy;
  const solid = tone === "solid";
  const text: TextStyle = { fontFamily: font.sansBold, fontSize: 16, color: solid ? color.ink : color.white };
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!off, busy: !!busy }}
      disabled={off}
      onPress={() => { Haptics.selectionAsync().catch(() => {}); onPress(); }}
      style={({ pressed }) => [{
        height: 56, borderRadius: 28, paddingLeft: arrow ? 24 : 24, paddingRight: arrow ? 6 : 24, flexDirection: "row", alignItems: "center", justifyContent: arrow ? "space-between" : "center",
        backgroundColor: solid ? color.white : "transparent", borderWidth: solid ? 0 : 1, borderColor: color.line, opacity: off ? 0.5 : pressed ? 0.85 : 1,
      }, style]}
    >
      <RNText style={text}>{label}</RNText>
      {arrow ? (
        <View style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: solid ? color.ink : color.surfaceHigh, alignItems: "center", justifyContent: "center" }}>
          {busy ? <ActivityIndicator color={color.white} /> : <Ionicons name="arrow-forward" size={20} color={color.white} />}
        </View>
      ) : busy ? <ActivityIndicator color={solid ? color.ink : color.white} style={{ marginLeft: 12 }} /> : null}
    </Pressable>
  );
}

export function Chip({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "good" | "warn" | "bad" }) {
  const c = { neutral: color.muted, good: color.good, warn: color.warn, bad: color.bad }[tone];
  return (
    <View style={{ alignSelf: "flex-start", borderRadius: 999, borderWidth: 1, borderColor: c + "55", backgroundColor: c + "1a", paddingHorizontal: 10, paddingVertical: 4 }}>
      <RNText style={{ fontFamily: font.sansMedium, fontSize: 12, color: c }}>{label}</RNText>
    </View>
  );
}

export function ErrorLine({ message }: { message: string | null }) {
  if (!message) return null;
  return <RNText accessibilityRole="alert" style={{ fontFamily: font.sans, fontSize: 14, color: color.bad }}>{message}</RNText>;
}
