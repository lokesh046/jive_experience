import { Inter_400Regular, Inter_500Medium, Inter_600SemiBold, useFonts as useInter } from "@expo-google-fonts/inter";
import { Newsreader_400Regular, Newsreader_500Medium, useFonts as useSerif } from "@expo-google-fonts/newsreader";
import { DarkTheme, Stack, ThemeProvider, useRouter } from "expo-router";
import * as Notifications from "expo-notifications";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { AuthProvider, useAuth } from "@/lib/auth";
import { enablePush, routeFor } from "@/lib/push";
import { color } from "@/theme";

SplashScreen.preventAutoHideAsync();

const theme = { ...DarkTheme, colors: { ...DarkTheme.colors, background: color.bg, card: color.bg, border: color.line, primary: color.white } };

/** Signed-out people can only reach the sign-in screens; signed-in people can only reach the app. */
function Gate() {
  const { status } = useAuth();
  const router = useRouter();
  useEffect(() => { if (status !== "loading") SplashScreen.hideAsync(); }, [status]);
  // A phone that already agreed keeps telling us who it belongs to. Never ask at launch.
  useEffect(() => {
    if (status === "signedIn") enablePush(false).catch(() => {});
  }, [status]);

  // Tapping a push opens what it is about.
  useEffect(() => {
    const open = (r: Notifications.NotificationResponse) => {
      const url = r.notification.request.content.data?.url;
      router.push(routeFor(typeof url === "string" ? url : null) as any);
    };
    const sub = Notifications.addNotificationResponseReceivedListener(open);
    const last = Notifications.getLastNotificationResponse();
    if (last && status === "signedIn") open(last);
    return () => sub.remove();
  }, [router, status]);

  if (status === "loading") return null;   // the splash stays up until we know who this is
  const inApp = status === "signedIn";
  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: color.bg } }}>
      <Stack.Protected guard={!inApp}>
        <Stack.Screen name="(auth)" />
      </Stack.Protected>
      <Stack.Protected guard={inApp}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="event/[slug]" />
        <Stack.Screen name="checkout/[reference]" options={{ gestureEnabled: false }} />
        <Stack.Screen name="confirmed/[reference]" options={{ gestureEnabled: false }} />
        <Stack.Screen name="ticket/[reference]" />
        <Stack.Screen name="notifications" />
        <Stack.Screen name="phone" />
        <Stack.Screen name="box-office" />
      </Stack.Protected>
    </Stack>
  );
}

export default function Root() {
  const [serif] = useSerif({ Newsreader_400Regular, Newsreader_500Medium });
  const [sans] = useInter({ Inter_400Regular, Inter_500Medium, Inter_600SemiBold });
  const ready = serif && sans;
  if (!ready) return null;
  return (
    <ThemeProvider value={theme}>
      <StatusBar style="light" />
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </ThemeProvider>
  );
}
