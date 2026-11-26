import * as Calendar from "expo-calendar/legacy";
import * as Haptics from "expo-haptics";
import { ActionSheetIOS, Alert, Linking, Platform } from "react-native";

export interface Place { name: string; latitude?: number | null; longitude?: number | null; address?: string }

const destination = (p: Place) =>
  p.latitude != null && p.longitude != null ? `${p.latitude},${p.longitude}` : p.address || p.name;

/** Directions in the phone's own maps app. iPhone asks which one; Android opens its maps app. */
export async function openDirections(p: Place) {
  const q = encodeURIComponent(destination(p));
  const label = encodeURIComponent(p.name);
  const apple = `https://maps.apple.com/?daddr=${q}&dirflg=d`;
  const google = `https://www.google.com/maps/dir/?api=1&destination=${q}`;
  const open = (url: string) => Linking.openURL(url).catch(() => Alert.alert("Could not open Maps", "Try again, or search for the venue in your maps app."));

  if (Platform.OS === "ios") {
    ActionSheetIOS.showActionSheetWithOptions(
      { title: "Directions to " + p.name, options: ["Apple Maps", "Google Maps", "Cancel"], cancelButtonIndex: 2 },
      (i) => { if (i === 0) void open(apple); if (i === 1) void open(google); },
    );
    return;
  }
  // geo: opens whatever maps app the phone prefers; the web link is the fallback.
  const geo = p.latitude != null && p.longitude != null ? `geo:${p.latitude},${p.longitude}?q=${p.latitude},${p.longitude}(${label})` : `geo:0,0?q=${q}`;
  try { await Linking.openURL(geo); } catch { void open(google); }
}

export interface CalendarNight { title: string; subtitle?: string | null; starts_at: string; ends_at?: string | null; where: string; url?: string }

const DEFAULT_LENGTH_MS = 3 * 60 * 60 * 1000;

/** Opens the phone's own "new event" screen, filled in, with reminders. The person saves it there. */
export async function addToCalendar(n: CalendarNight): Promise<boolean> {
  try {
    if (Platform.OS === "ios") {
      const perm = await Calendar.requestCalendarPermissionsAsync();
      if (!perm.granted) {
        Alert.alert("Calendar access is off", "Allow JIVE to use your calendar in Settings to save this night.");
        return false;
      }
    }
    const start = new Date(n.starts_at);
    const end = n.ends_at && new Date(n.ends_at) > start ? new Date(n.ends_at) : new Date(start.getTime() + DEFAULT_LENGTH_MS);
    const res = await Calendar.createEventInCalendarAsync({
      title: n.title,
      startDate: start,
      endDate: end,
      location: n.where,
      notes: [n.subtitle, n.url ? `Tickets and details: ${n.url}` : null].filter(Boolean).join("\n\n"),
      alarms: [{ relativeOffset: -1440 }, { relativeOffset: -120 }],
    });
    const saved = (res as { action?: string }).action === "saved";
    if (saved) Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    return saved;
  } catch {
    Alert.alert("Could not open your calendar", "Try again in a moment.");
    return false;
  }
}
