import { Stack, useRouter } from "expo-router";
import { useState } from "react";
import { KeyboardAvoidingView, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Body, ErrorLine, H1, Label, PillButton } from "@/components/ui";
import { api } from "@/lib/api";
import { color, font } from "@/theme";

/** A phone number is needed once, before the first booking. */
export default function Phone() {
  const router = useRouter();
  const [value, setValue] = useState("+91 ");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    const v = value.replace(/[\s-]/g, "");
    if (!/^\+[1-9][0-9]{7,14}$/.test(v)) return setError("Enter your number with the country code, like +91 98765 43210.");
    setBusy(true); setError(null);
    try { await api("auth/phone", { method: "PUT", json: { phone_e164: v } }); router.back(); }
    catch (e: any) { setError(e?.message ?? "Could not save the number."); }
    finally { setBusy(false); }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }}>
      <Stack.Screen options={{ headerShown: false, presentation: "modal" }} />
      <KeyboardAvoidingView style={{ flex: 1, padding: 24, gap: 18, justifyContent: "center" }} behavior="padding">
        <H1>Your phone number</H1>
        <Body>We need it once, to keep ticket buying fair. It is only used for your bookings.</Body>
        <View style={{ gap: 8 }}>
          <Label>Mobile number</Label>
          <TextInput value={value} onChangeText={setValue} keyboardType="phone-pad" textContentType="telephoneNumber" autoComplete="tel" autoFocus
            style={{ height: 56, borderRadius: 28, paddingHorizontal: 22, backgroundColor: color.surface, color: color.white, fontFamily: font.sans, fontSize: 16, borderWidth: 1, borderColor: color.line }} />
        </View>
        <ErrorLine message={error} />
        <PillButton label="Save and go back" onPress={save} busy={busy} />
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
