import { Ionicons } from "@expo/vector-icons";
import Constants from "expo-constants";
import { useRouter } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Modal, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Photo } from "@/components/Photo";
import { Body, Chip, ErrorLine, H2, Label, PillButton } from "@/components/ui";
import { api } from "@/lib/api";
import { canTakePhoto, chooseAvatar, removeAvatar } from "@/lib/avatar";
import { useAuth } from "@/lib/auth";
import { SITE_URL } from "@/lib/config";
import type { AuthUser } from "@/lib/types";
import { useUnread } from "@/lib/useUnread";
import { color, font } from "@/theme";

const NAME_MAX = 120;

function initials(name: string | null, email: string) {
  const parts = (name ?? email).trim().split(/[\s@.]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (name && parts[1] ? parts[1][0] : "")).toUpperCase();
}

/** A titled group of rows in one rounded card. */
function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={{ gap: 8 }}>
      <Label style={{ marginLeft: 6 }}>{title}</Label>
      <View style={{ borderRadius: 22, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line, overflow: "hidden" }}>{children}</View>
    </View>
  );
}

function Row({ label, value, onPress, accent, last }: { label: string; value?: string; onPress: () => void; accent?: boolean; last?: boolean }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" style={({ pressed }) => ({ flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: 18, paddingVertical: 16, borderBottomWidth: last ? 0 : 1, borderColor: color.line, backgroundColor: pressed ? color.surfaceHigh : "transparent" })}>
      <Text style={{ fontFamily: font.sansMedium, fontSize: 16, color: color.white }}>{label}</Text>
      <View style={{ flexDirection: "row", gap: 8, alignItems: "center", flexShrink: 1 }}>
        {!!value && <Text numberOfLines={1} style={{ fontFamily: font.sansMedium, fontSize: 14, color: accent ? color.amber : color.muted, flexShrink: 1 }}>{value}</Text>}
        <Ionicons name="chevron-forward" size={18} color={color.faint} />
      </View>
    </Pressable>
  );
}

export default function Profile() {
  const { user, signOut, updateUser } = useAuth();
  const router = useRouter();
  const unread = useUnread();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [photoMenu, setPhotoMenu] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoError, setPhotoError] = useState<string | null>(null);
  if (!user) return null;

  const role = user.role === "EVENT_STAFF" ? "Gate staff" : user.role === "ADMIN" ? "Admin" : "Customer";
  const web = (path: string) => WebBrowser.openBrowserAsync(`${SITE_URL}${path}`, { toolbarColor: "#0a0a0a", controlsColor: "#ffffff" }).catch(() => {});

  async function changePhoto(run: () => Promise<AuthUser | null>) {
    setPhotoMenu(false); setPhotoBusy(true); setPhotoError(null);
    try {
      const u = await run();
      if (u) updateUser({ ...user!, avatar_url: u.avatar_url });
    } catch (e: any) {
      setPhotoError(e?.code === "IMAGE_TOO_LARGE" ? "That photo is too large. Try another." : e?.message ?? "Could not update your photo.");
    } finally { setPhotoBusy(false); }
  }

  function startEdit() { setName(user!.full_name ?? ""); setError(null); setEditing(true); }

  async function save() {
    const clean = name.trim();
    if (!clean) return setError("Enter your name.");
    if (clean === (user!.full_name ?? "")) return setEditing(false);
    setBusy(true); setError(null);
    try {
      const u = await api<AuthUser>("users/me", { method: "PATCH", json: { full_name: clean } });
      updateUser({ ...user!, full_name: u.full_name });
      setEditing(false);
    } catch (e: any) { setError(e?.message ?? "Could not save your name."); }
    finally { setBusy(false); }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }} edges={["top"]}>
      <ScrollView contentContainerStyle={{ padding: 20, gap: 24, paddingBottom: 40 }}>
        {/* Who you are, centred. */}
        <View style={{ alignItems: "center", gap: 10, paddingTop: 8 }}>
          <Pressable onPress={() => setPhotoMenu(true)} accessibilityRole="button" accessibilityLabel="Change profile photo" disabled={photoBusy}>
            {user.avatar_url ? (
              <Photo source={user.avatar_url} accessibilityLabel="Your photo" style={{ width: 96, height: 96, borderRadius: 48, opacity: photoBusy ? 0.5 : 1 }} />
            ) : (
              <View style={{ width: 96, height: 96, borderRadius: 48, borderWidth: 1, borderColor: color.line, backgroundColor: color.surface, alignItems: "center", justifyContent: "center", opacity: photoBusy ? 0.5 : 1 }}>
                <Text style={{ fontFamily: font.serif, fontSize: 36, color: color.white }}>{initials(user.full_name, user.email)}</Text>
              </View>
            )}
            <View style={{ position: "absolute", right: -2, bottom: -2, width: 32, height: 32, borderRadius: 16, backgroundColor: color.white, alignItems: "center", justifyContent: "center", borderWidth: 3, borderColor: color.bg }}>
              {photoBusy ? <ActivityIndicator size="small" color={color.ink} /> : <Ionicons name="camera" size={16} color={color.ink} />}
            </View>
          </Pressable>
          <ErrorLine message={photoError} />
          <Pressable onPress={startEdit} accessibilityRole="button" accessibilityLabel="Edit name" hitSlop={8} style={{ flexDirection: "row", alignItems: "center", gap: 8, maxWidth: "100%" }}>
            <Text numberOfLines={2} style={{ fontFamily: font.serif, fontSize: 30, lineHeight: 34, color: color.white, textAlign: "center", flexShrink: 1 }}>{user.full_name ?? "Add your name"}</Text>
            <Ionicons name="pencil" size={16} color={color.muted} />
          </Pressable>
          <Body style={{ fontSize: 15 }}>{user.email}</Body>
          <View style={{ alignSelf: "center" }}><Chip label={role} /></View>
        </View>

        <Group title="Account">
          <Row label="Name" value={user.full_name ?? "Add"} onPress={startEdit} />
          <Row label="Phone number" value={user.phone_e164 ?? "Add"} onPress={() => router.push("/phone")} last />
        </Group>

        <Group title="Activity">
          <Row label="My tickets" onPress={() => router.push("/tickets")} />
          <Row label="Notifications" value={unread > 0 ? `${unread} new` : undefined} accent onPress={() => router.push("/notifications")} last />
        </Group>

        <Group title="About">
          <Row label="Cancellation policy" onPress={() => web("/cancellation-policy")} />
          <Row label="Terms" onPress={() => web("/terms")} />
          <Row label="Privacy" onPress={() => web("/privacy")} last />
        </Group>

        <View style={{ gap: 12 }}>
          <PillButton
            label="Sign out" tone="ghost" arrow={false}
            onPress={() => Alert.alert("Sign out?", "You will need a new code to sign back in.", [{ text: "Stay signed in", style: "cancel" }, { text: "Sign out", style: "destructive", onPress: signOut }])}
          />
          <Text style={{ fontFamily: font.sans, fontSize: 12, color: color.faint, textAlign: "center" }}>JIVE {Constants.expoConfig?.version ?? ""}</Text>
        </View>
      </ScrollView>

      <Modal visible={photoMenu} transparent animationType="fade" onRequestClose={() => setPhotoMenu(false)}>
        <Pressable onPress={() => setPhotoMenu(false)} style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.7)", justifyContent: "flex-end", padding: 20 }}>
          <Pressable style={{ padding: 22, borderRadius: 28, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line, gap: 12 }}>
            <H2>Profile photo</H2>
            <PillButton label="Choose from your photos" arrow={false} onPress={() => changePhoto(() => chooseAvatar("library"))} />
            {canTakePhoto && <PillButton label="Take a photo" tone="ghost" arrow={false} onPress={() => changePhoto(() => chooseAvatar("camera"))} />}
            {!!user.avatar_url && <PillButton label="Remove photo" tone="ghost" arrow={false} onPress={() => changePhoto(removeAvatar)} />}
            <PillButton label="Cancel" tone="ghost" arrow={false} onPress={() => setPhotoMenu(false)} />
          </Pressable>
        </Pressable>
      </Modal>

      <Modal visible={editing} transparent animationType="fade" onRequestClose={() => setEditing(false)}>
        <KeyboardAvoidingView behavior="padding" style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.7)", justifyContent: "center", padding: 20 }}>
          <View style={{ padding: 22, borderRadius: 28, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line, gap: 14 }}>
            <H2>Your name</H2>
            <Body style={{ fontSize: 14 }}>This is the name on your account and your tickets.</Body>
            <TextInput
              value={name}
              onChangeText={(t) => setName(t.slice(0, NAME_MAX))}
              autoFocus
              placeholder="Full name"
              placeholderTextColor={color.faint}
              autoComplete="name"
              textContentType="name"
              returnKeyType="done"
              onSubmitEditing={save}
              maxLength={NAME_MAX}
              accessibilityLabel="Full name"
              style={{ height: 52, borderRadius: 26, paddingHorizontal: 20, backgroundColor: color.bg, color: color.white, fontFamily: font.sans, fontSize: 16, borderWidth: 1, borderColor: color.line }}
            />
            <ErrorLine message={error} />
            <PillButton label="Save" onPress={save} busy={busy} />
            <PillButton label="Cancel" tone="ghost" arrow={false} onPress={() => setEditing(false)} />
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}
