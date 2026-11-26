import { Ionicons } from "@expo/vector-icons";
import Constants from "expo-constants";
import { useRouter } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { Alert, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Body, Chip, H1, PillButton } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { SITE_URL } from "@/lib/config";
import { useUnread } from "@/lib/useUnread";
import { color, font } from "@/theme";

function initials(name: string | null, email: string) {
  const src = (name ?? email).trim();
  const parts = src.split(/[\s@.]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (name && parts[1] ? parts[1][0] : "")).toUpperCase();
}

export default function Profile() {
  const { user, signOut } = useAuth();
  const router = useRouter();
  const unread = useUnread();
  if (!user) return null;
  const role = user.role === "EVENT_STAFF" ? "Gate staff" : user.role === "ADMIN" ? "Admin" : "Customer";
  const web = (path: string) => WebBrowser.openBrowserAsync(`${SITE_URL}${path}`, { toolbarColor: "#0a0a0a", controlsColor: "#ffffff" }).catch(() => {});

  const Row = ({ label, value, onPress, accent }: { label: string; value?: string; onPress: () => void; accent?: boolean }) => (
    <Pressable onPress={onPress} accessibilityRole="button" style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 16, borderBottomWidth: 1, borderColor: color.line }}>
      <Text style={{ fontFamily: font.sansMedium, fontSize: 16, color: color.white }}>{label}</Text>
      <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
        {!!value && <Text style={{ fontFamily: font.sansMedium, fontSize: 14, color: accent ? color.amber : color.muted }}>{value}</Text>}
        <Ionicons name="chevron-forward" size={18} color={color.faint} />
      </View>
    </Pressable>
  );

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }} edges={["top"]}>
      <ScrollView contentContainerStyle={{ padding: 20, gap: 14, paddingBottom: 40 }}>
        <View style={{ width: 72, height: 72, borderRadius: 36, borderWidth: 1, borderColor: color.line, backgroundColor: color.surface, alignItems: "center", justifyContent: "center" }}>
          <Text style={{ fontFamily: font.serif, fontSize: 28, color: color.white }}>{initials(user.full_name, user.email)}</Text>
        </View>
        <H1>{user.full_name ?? "Your account"}</H1>
        <Body>{user.email}</Body>
        <View><Chip label={role} /></View>

        <View style={{ marginTop: 10, borderTopWidth: 1, borderColor: color.line }}>
          <Row label="My tickets" onPress={() => router.push("/tickets")} />
          <Row label="Notifications" value={unread > 0 ? `${unread} new` : undefined} accent onPress={() => router.push("/notifications")} />
          <Row label="Phone number" value={user.phone_e164 ?? "Add"} onPress={() => router.push("/phone")} />
          <Row label="Cancellation policy" onPress={() => web("/cancellation-policy")} />
          <Row label="Terms" onPress={() => web("/terms")} />
          <Row label="Privacy" onPress={() => web("/privacy")} />
        </View>

        <PillButton
          label="Sign out" tone="ghost" arrow={false} style={{ marginTop: 16 }}
          onPress={() => Alert.alert("Sign out?", "You will need a new code to sign back in.", [{ text: "Stay signed in", style: "cancel" }, { text: "Sign out", style: "destructive", onPress: signOut }])}
        />
        <Text style={{ fontFamily: font.sans, fontSize: 12, color: color.faint, textAlign: "center", marginTop: 8 }}>JIVE {Constants.expoConfig?.version ?? ""}</Text>
      </ScrollView>
    </SafeAreaView>
  );
}
