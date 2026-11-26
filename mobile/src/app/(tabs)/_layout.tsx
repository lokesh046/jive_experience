import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import { useAuth } from "@/lib/auth";
import { color, font } from "@/theme";

type Icon = keyof typeof Ionicons.glyphMap;
const tab = (title: string, icon: Icon, focused: Icon) => ({
  title,
  tabBarIcon: ({ focused: f, color: c, size }: { focused: boolean; color: any; size: number }) => <Ionicons name={f ? focused : icon} size={size} color={c} />,
});

export default function TabsLayout() {
  const { user } = useAuth();
  const staff = user?.role === "EVENT_STAFF" || user?.role === "ADMIN";
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: color.white,
        tabBarInactiveTintColor: color.faint,
        tabBarStyle: { backgroundColor: color.bg, borderTopColor: color.line },
        tabBarLabelStyle: { fontFamily: font.sansMedium, fontSize: 11 },
        sceneStyle: { backgroundColor: color.bg },
      }}
    >
      <Tabs.Screen name="index" options={tab("Home", "home-outline", "home")} />
      <Tabs.Screen name="events" options={tab("Events", "calendar-outline", "calendar")} />
      <Tabs.Screen name="tickets" options={tab("Tickets", "ticket-outline", "ticket")} />
      <Tabs.Screen name="scan" options={{ ...tab("Scan", "scan-outline", "scan"), href: staff ? undefined : null }} />
      <Tabs.Screen name="profile" options={tab("Profile", "person-outline", "person")} />
    </Tabs>
  );
}
