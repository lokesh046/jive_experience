import { Stack } from "expo-router";
import { color } from "@/theme";

export const unstable_settings = { anchor: "signin" };

export default function AuthLayout() {
  return <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: color.bg } }} />;
}
