import { Ionicons } from "@expo/vector-icons";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as Device from "expo-device";
import * as Haptics from "expo-haptics";
import { useFocusEffect, useRouter } from "expo-router";
import * as SecureStore from "expo-secure-store";
import { useCallback, useEffect, useRef, useState } from "react";
import { Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { ScanResultSheet } from "@/components/ScanResultSheet";
import { Body, ErrorLine, H1, Label, PillButton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { whenIs, type When } from "@/lib/scan";
import type { AssignedEvent, Attendance, ScanResponse } from "@/lib/types";
import { color, font } from "@/theme";

const STORE = "jive_scan_event";

export default function Scan() {
  const { user } = useAuth();
  const router = useRouter();
  const [events, setEvents] = useState<AssignedEvent[] | null>(null);
  const [eventId, setEventId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());

  useFocusEffect(useCallback(() => {
    api<AssignedEvent[]>("scanner/events")
      .then((l) => { setEvents(l); setError(null); })
      .catch((e) => { setEvents([]); setError(e instanceof ApiError ? e.message : "Could not load your events."); });
  }, []));
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 30_000); return () => clearInterval(t); }, []);

  const open = (id: string) => { SecureStore.setItemAsync(STORE, id).catch(() => {}); setEventId(id); };
  const event = events?.find((e) => e.event_id === eventId) ?? null;

  if (event) return <Scanner event={event} now={now} onLeave={() => setEventId(null)} />;

  const rows = (events ?? []).map((e) => ({ e, w: whenIs(e, now) }));
  const active = rows.filter((r) => r.w.phase !== "ended");
  const ended = rows.filter((r) => r.w.phase === "ended");
  const card = ({ e, w }: { e: AssignedEvent; w: When }) => (
    <Pressable key={e.event_id} onPress={() => open(e.event_id)} accessibilityRole="button"
      style={{ padding: 16, borderRadius: 20, backgroundColor: color.surface, borderWidth: 1, borderColor: w.phase === "live" ? color.good : color.line, gap: 4, opacity: w.phase === "ended" ? 0.6 : 1 }}>
      <Text style={{ fontFamily: font.sansBold, fontSize: 12, letterSpacing: 1.2, textTransform: "uppercase", color: w.phase === "live" ? color.good : color.muted }}>{w.label}</Text>
      <Text style={{ fontFamily: font.serif, fontSize: 22, color: color.white }}>{e.title}</Text>
      <Body style={{ fontSize: 14 }}>{w.day} · {w.range}</Body>
      <Body style={{ fontSize: 14 }}>{e.venue_name}, {e.city}</Body>
    </Pressable>
  );

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }} edges={["top"]}>
      <ScrollView contentContainerStyle={{ padding: 20, gap: 14 }}>
        <Label>{user ? `Signed in as ${user.full_name ?? user.email}` : " "}</Label>
        <H1>Your events</H1>
        <Body>Tap an event to start scanning. Only events you are assigned to are shown.</Body>
        {events === null && <Body>Loading…</Body>}
        <ErrorLine message={error} />
        {events && events.length === 0 && !error && <Body>You are not assigned to any event. Ask an administrator to add you.</Body>}
        {events && events.length > 0 && active.length === 0 && <Body>Nothing to scan right now. Events appear here from an hour before they start.</Body>}
        {active.map(card)}
        {ended.length > 0 && <><Label style={{ marginTop: 10 }}>Earlier</Label>{ended.map(card)}</>}
        {events && events.length > 0 && <PillButton label="Box office" tone="ghost" arrow={false} onPress={() => router.push("/box-office")} style={{ marginTop: 10 }} />}
      </ScrollView>
    </SafeAreaView>
  );
}

function Scanner({ event, now, onLeave }: { event: AssignedEvent; now: number; onLeave: () => void }) {
  const [perm, askPerm] = useCameraPermissions();
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attendance, setAttendance] = useState<Attendance | null>(null);
  const [torch, setTorch] = useState(false);
  const [typing, setTyping] = useState(false);
  const [manual, setManual] = useState("");
  const busy = useRef(false);
  const last = useRef({ code: "", at: 0 });
  const when = whenIs(event, now);

  useEffect(() => {
    const load = () => api<Attendance>(`scanner/events/${event.event_id}/attendance`).then(setAttendance).catch(() => {});
    load();
    const t = setInterval(load, 20_000);
    return () => clearInterval(t);
  }, [event.event_id]);

  const submit = useCallback(async (code: string) => {
    if (busy.current) return;
    const t = Date.now();
    // The camera sees the same code many times a second: ignore repeats for a moment.
    if (code === last.current.code && t - last.current.at < 3000) return;
    last.current = { code, at: t };
    busy.current = true;
    try {
      const r = await api<ScanResponse>("scanner/scan", { method: "POST", json: { qr_token: code, event_id: event.event_id, device_label: `${Platform.OS} ${Device.modelName ?? ""}`.trim().slice(0, 120) } });
      Haptics.notificationAsync(r.ok ? Haptics.NotificationFeedbackType.Success : Haptics.NotificationFeedbackType.Error).catch(() => {});
      setResult(r);
      api<Attendance>(`scanner/events/${event.event_id}/attendance`).then(setAttendance).catch(() => {});
    } catch (e) {
      busy.current = false;
      setError(e instanceof ApiError ? e.message : "Could not reach the server. Check the connection and scan again.");
    }
  }, [event.event_id]);

  const dismiss = useCallback(() => { setResult(null); setError(null); busy.current = false; }, []);
  useEffect(() => {
    if (result?.ok) { const t = setTimeout(dismiss, 1800); return () => clearTimeout(t); }
  }, [result, dismiss]);

  const expected = attendance ? attendance.total - attendance.cancelled - attendance.refunded : null;

  return (
    <View style={{ flex: 1, backgroundColor: "#000" }}>
      {perm?.granted ? (
        <CameraView
          style={{ flex: 1 }}
          facing="back"
          enableTorch={torch}
          barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
          onBarcodeScanned={result || typing ? undefined : (e) => void submit(e.data)}
        />
      ) : (
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: 28, gap: 14 }}>
          <Body style={{ textAlign: "center" }}>{perm && !perm.canAskAgain ? "Camera access is blocked. Allow it in your phone's Settings, or type the code instead." : "JIVE needs the camera to scan tickets."}</Body>
          {perm?.canAskAgain !== false && <PillButton label="Allow the camera" onPress={() => askPerm()} style={{ alignSelf: "stretch" }} />}
        </View>
      )}

      <SafeAreaView pointerEvents="box-none" style={{ position: "absolute", left: 0, right: 0, top: 0, bottom: 0, justifyContent: "space-between" }}>
        <View style={{ margin: 16, padding: 14, borderRadius: 20, backgroundColor: "rgba(10,10,10,0.8)", flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <View style={{ flex: 1, paddingRight: 12 }}>
            <Text style={{ fontFamily: font.sansBold, fontSize: 16, color: color.white }} numberOfLines={1}>{event.title}</Text>
            <Text style={{ fontFamily: font.sans, fontSize: 13, color: color.muted }}>{when.day} · {when.range}</Text>
          </View>
          <View accessibilityLiveRegion="polite" style={{ alignItems: "flex-end" }}>
            <Text style={{ fontFamily: font.serif, fontSize: 34, color: color.white }}>{attendance ? attendance.checked_in : "–"}</Text>
            <Text style={{ fontFamily: font.sans, fontSize: 12, color: color.muted }}>{expected !== null ? `of ${expected} in` : "in"}</Text>
          </View>
        </View>

        {perm?.granted && !typing && (
          <View pointerEvents="none" style={{ alignSelf: "center", width: 240, height: 240 }}>
            {[{ top: 0, left: 0, borderTopWidth: 4, borderLeftWidth: 4 }, { top: 0, right: 0, borderTopWidth: 4, borderRightWidth: 4 }, { bottom: 0, left: 0, borderBottomWidth: 4, borderLeftWidth: 4 }, { bottom: 0, right: 0, borderBottomWidth: 4, borderRightWidth: 4 }].map((s, i) => (
              <View key={i} style={[{ position: "absolute", width: 44, height: 44, borderColor: color.white, borderRadius: 8 }, s]} />
            ))}
          </View>
        )}

        <View style={{ padding: 16, gap: 10, backgroundColor: "rgba(10,10,10,0.8)" }}>
          {error && !result && (
            <View style={{ flexDirection: "row", justifyContent: "space-between", gap: 10 }}>
              <View style={{ flex: 1 }}><ErrorLine message={error} /></View>
              <Pressable onPress={dismiss} accessibilityRole="button"><Text style={{ fontFamily: font.sansMedium, color: color.white }}>Dismiss</Text></Pressable>
            </View>
          )}
          {typing && (
            <View style={{ flexDirection: "row", gap: 8 }}>
              <TextInput value={manual} onChangeText={setManual} placeholder="Ticket code" placeholderTextColor={color.faint} autoCapitalize="none" autoCorrect={false} autoFocus
                style={{ flex: 1, height: 48, borderRadius: 24, paddingHorizontal: 18, backgroundColor: color.surface, color: color.white, fontFamily: font.sans, borderWidth: 1, borderColor: color.line }} />
              <Pressable onPress={() => { if (manual.trim()) { void submit(manual.trim()); setManual(""); setTyping(false); } }} accessibilityRole="button"
                style={{ height: 48, paddingHorizontal: 22, borderRadius: 24, backgroundColor: color.white, alignItems: "center", justifyContent: "center" }}>
                <Text style={{ fontFamily: font.sansBold, color: color.ink }}>Check</Text>
              </Pressable>
            </View>
          )}
          <View style={{ flexDirection: "row", gap: 10 }}>
            <Chip icon={torch ? "flash" : "flash-outline"} label={torch ? "Light on" : "Light"} onPress={() => setTorch((t) => !t)} />
            <Chip icon="keypad-outline" label={typing ? "Use camera" : "Type code"} onPress={() => setTyping((t) => !t)} />
            <Chip icon="chevron-back" label="Events" onPress={onLeave} />
          </View>
        </View>
      </SafeAreaView>

      {result && <ScanResultSheet r={result} onDismiss={dismiss} />}
    </View>
  );
}

function Chip({ icon, label, onPress }: { icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" style={{ flex: 1, height: 44, borderRadius: 22, backgroundColor: color.surfaceHigh, flexDirection: "row", gap: 6, alignItems: "center", justifyContent: "center" }}>
      <Ionicons name={icon} size={18} color={color.white} />
      <Text style={{ fontFamily: font.sansMedium, fontSize: 14, color: color.white }}>{label}</Text>
    </Pressable>
  );
}
