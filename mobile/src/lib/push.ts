import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import { api } from "./api";

const TOKEN_KEY = "jive_push_token";

// Show the banner even when the app is open.
Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
});

/** What the website's links mean inside the app. */
export function routeFor(link: string | null | undefined): string {
  if (!link) return "/notifications";
  const path = link.split("?")[0].replace(/\/+$/, "");
  let m = path.match(/^\/tickets\/([^/]+)$/);
  if (m) return `/ticket/${m[1]}`;
  if (path === "/tickets") return "/tickets";
  m = path.match(/^\/events\/([^/#]+)/);
  if (m) return `/event/${m[1]}`;
  m = path.match(/^\/checkout\/([^/]+)$/);
  if (m) return `/checkout/${m[1]}`;
  return "/notifications";
}

export type PushState = "on" | "off" | "denied" | "unsupported";

export async function pushState(): Promise<PushState> {
  if (!Device.isDevice) return "unsupported";
  const p = await Notifications.getPermissionsAsync();
  if (p.status === "denied" && !p.canAskAgain) return "denied";
  const token = await SecureStore.getItemAsync(TOKEN_KEY);
  return p.granted && token ? "on" : "off";
}

/** Asks for permission (when `ask`), then tells the server which phone this is. */
export async function enablePush(ask: boolean): Promise<PushState> {
  if (!Device.isDevice) return "unsupported";
  let p = await Notifications.getPermissionsAsync();
  if (!p.granted && ask) p = await Notifications.requestPermissionsAsync();
  if (!p.granted) return p.canAskAgain ? "off" : "denied";
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("default", { name: "JIVE", importance: Notifications.AndroidImportance.HIGH });
  }
  const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
  const { data: token } = await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined);
  await api("notifications/push/device", { method: "POST", json: { token, platform: Platform.OS } });
  await SecureStore.setItemAsync(TOKEN_KEY, token);
  return "on";
}

export async function disablePush() {
  const token = await SecureStore.getItemAsync(TOKEN_KEY);
  if (token) { try { await api("notifications/push/unsubscribe", { method: "POST", json: { endpoint: token } }); } catch {} }
  await SecureStore.deleteItemAsync(TOKEN_KEY);
}
