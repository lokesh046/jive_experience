import { Stack, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, FlatList, Pressable, RefreshControl, Switch, Text, View } from "react-native";
import { Body, ErrorLine, H1, H2, Label, PillButton } from "@/components/ui";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { disablePush, enablePush, pushState, routeFor, type PushState } from "@/lib/push";
import type { AppNotification, NotificationFeed, NotificationPreference } from "@/lib/types";
import { color, font } from "@/theme";

export default function Notifications() {
  const router = useRouter();
  const [items, setItems] = useState<AppNotification[] | null>(null);
  const [unread, setUnread] = useState(0);
  const [next, setNext] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<NotificationPreference[]>([]);
  const [push, setPush] = useState<PushState>("off");
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const f = await api<NotificationFeed>("notifications?limit=30");
      setItems(f.items); setUnread(f.unread); setNext(f.next_before); setError(null);
    } catch (e: any) { setError(e?.message ?? "We could not load your notifications."); }
    api<NotificationPreference[]>("notifications/preferences").then(setPrefs).catch(() => {});
    setPush(await pushState());
  }, []);
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  async function more() {
    if (!next) return;
    try {
      const f = await api<NotificationFeed>(`notifications?limit=30&before=${encodeURIComponent(next)}`);
      setItems((cur) => [...(cur ?? []), ...f.items]); setNext(f.next_before);
    } catch {}
  }

  async function open(n: AppNotification) {
    if (!n.read) {
      setItems((cur) => cur && cur.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
      setUnread((u) => Math.max(0, u - 1));
      api("notifications/read", { method: "POST", json: { ids: [n.id] } }).catch(() => {});
    }
    const to = routeFor(n.link);
    if (to !== "/notifications") router.push(to as any);
  }

  async function readAll() {
    try { await api("notifications/read-all", { method: "POST", json: {} }); setUnread(0); setItems((cur) => cur && cur.map((n) => ({ ...n, read: true }))); }
    catch (e: any) { setError(e?.message ?? "Could not mark them read."); }
  }

  async function setPref(category: string, field: "in_app" | "email" | "push", value: boolean) {
    try { setPrefs(await api<NotificationPreference[]>("notifications/preferences", { method: "PUT", json: { changes: [{ category, [field]: value }] } })); }
    catch { void api<NotificationPreference[]>("notifications/preferences").then(setPrefs).catch(() => {}); }
  }

  async function togglePush() {
    setBusy(true); setError(null);
    try {
      if (push === "on") { await disablePush(); setPush("off"); }
      else {
        const s = await enablePush(true);
        setPush(s);
        if (s === "denied") Alert.alert("Notifications are off", "Turn them on for JIVE in your phone's Settings, then come back.");
        if (s === "unsupported") setError("Push works on a real phone, not a simulator.");
      }
    } catch (e: any) {
      setError(e?.message?.includes("projectId") ? "Push needs the app built with EAS. It does not work in Expo Go on Android." : (e?.message ?? "Could not turn notifications on."));
    } finally { setBusy(false); }
  }

  const prefRow = (p: NotificationPreference) => (
    <View key={p.category} style={{ paddingVertical: 14, borderTopWidth: 1, borderTopColor: color.line, gap: 8 }}>
      <Text style={{ fontFamily: font.sansBold, fontSize: 15, color: color.white }}>{p.label}</Text>
      <Body style={{ fontSize: 13 }}>{p.description}</Body>
      <Toggle label="In the app" value={p.in_app} onChange={(v) => setPref(p.category, "in_app", v)} />
      {p.email_choice && <Toggle label="Email" value={p.email} onChange={(v) => setPref(p.category, "email", v)} />}
      <Toggle label="Push on this phone" value={p.push} disabled={push !== "on"} onChange={(v) => setPref(p.category, "push", v)} />
    </View>
  );

  return (
    <View style={{ flex: 1, backgroundColor: color.bg }}>
      <Stack.Screen options={{ headerShown: true, headerTitle: "", headerStyle: { backgroundColor: color.bg }, headerTintColor: color.white, headerShadowVisible: false, headerBackButtonDisplayMode: "minimal" }} />
      <FlatList
        data={items ?? []}
        keyExtractor={(n) => n.id}
        contentContainerStyle={{ padding: 20, paddingBottom: 60 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={color.white} />}
        onEndReached={more}
        ListHeaderComponent={
          <View style={{ gap: 12, marginBottom: 16 }}>
            <H1>Notifications</H1>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Label>{unread > 0 ? `${unread} unread` : "All caught up"}</Label>
              {unread > 0 && <Pressable onPress={readAll} accessibilityRole="button" hitSlop={8}><Text style={{ fontFamily: font.sansMedium, color: color.white }}>Mark all read</Text></Pressable>}
            </View>
            <ErrorLine message={error} />
          </View>
        }
        ListEmptyComponent={<Body>{items === null ? "Loading…" : "Nothing yet. Updates about your bookings will show up here."}</Body>}
        renderItem={({ item: n }) => (
          <Pressable onPress={() => open(n)} accessibilityRole="button" style={{ flexDirection: "row", gap: 12, paddingVertical: 14, borderTopWidth: 1, borderTopColor: color.line }}>
            <View style={{ width: 10, paddingTop: 7 }}>{!n.read && <View accessibilityLabel="Unread" style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: color.amber }} />}</View>
            <View style={{ flex: 1, gap: 3 }}>
              <Text style={{ fontFamily: n.read ? font.sansMedium : font.sansBold, fontSize: 16, color: n.severity === "critical" ? color.bad : color.white }}>{n.title}</Text>
              {!!n.body && <Body style={{ fontSize: 14 }}>{n.body}</Body>}
              <Text style={{ fontFamily: font.sans, fontSize: 12, color: color.faint }}>{ago(n.created_at)}</Text>
            </View>
          </Pressable>
        )}
        ListFooterComponent={
          <View style={{ marginTop: 32, gap: 12 }}>
            <H2>How we reach you</H2>
            <PillButton label={push === "on" ? "Turn off push on this phone" : "Turn on push on this phone"} tone="ghost" arrow={false} busy={busy} onPress={togglePush} />
            {push === "denied" && <Body style={{ fontSize: 13 }}>Notifications are blocked for JIVE. Allow them in your phone's Settings.</Body>}
            {prefs.map(prefRow)}
          </View>
        }
      />
    </View>
  );
}

function Toggle({ label, value, onChange, disabled }: { label: string; value: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", opacity: disabled ? 0.45 : 1 }}>
      <Text style={{ fontFamily: font.sans, fontSize: 15, color: color.text }}>{label}</Text>
      <Switch value={value && !disabled} onValueChange={onChange} disabled={disabled} accessibilityLabel={label} trackColor={{ true: color.white, false: color.line }} thumbColor={value ? color.ink : color.muted} />
    </View>
  );
}
