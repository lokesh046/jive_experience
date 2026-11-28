import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import { KeyboardAvoidingView, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Body, ErrorLine, H1, Label, PillButton } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { color, font } from "@/theme";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function SignIn() {
  const { requestCode, googleSignIn } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [googleBusy, setGoogleBusy] = useState(false);

  async function submit() {
    const e = email.trim().toLowerCase();
    if (!EMAIL.test(e)) return setError("Enter a valid email address.");
    setBusy(true); setError(null);
    try {
      await requestCode(e);
      router.push({ pathname: "/code", params: { email: e } });
    } catch (err: any) {
      setError(err?.message ?? "Could not send the code.");
    } finally { setBusy(false); }
  }

  async function google() {
    setGoogleBusy(true); setError(null);
    try { await googleSignIn(); }   // the root gate moves us on once signed in
    catch (err: any) { setError(err?.message ?? "Could not sign in with Google."); }
    finally { setGoogleBusy(false); }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior="padding">
        <ScrollView contentContainerStyle={{ padding: 24, gap: 20, flexGrow: 1, justifyContent: "center" }} keyboardShouldPersistTaps="handled">
          <Body style={{ fontFamily: font.serif, fontSize: 34, color: color.white, letterSpacing: 6 }}>jive</Body>
          <View style={{ gap: 10, marginTop: 24 }}>
            <H1>Sign in</H1>
            <Body>One account for your tickets. We will email you a six digit code.</Body>
          </View>
          <Pressable onPress={google} disabled={googleBusy || busy} accessibilityRole="button" accessibilityLabel="Continue with Google"
            style={{ height: 56, borderRadius: 28, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line, flexDirection: "row", gap: 12, alignItems: "center", justifyContent: "center", opacity: googleBusy ? 0.6 : 1 }}>
            <Ionicons name="logo-google" size={20} color={color.white} />
            <Text style={{ fontFamily: font.sansBold, fontSize: 16, color: color.white }}>{googleBusy ? "Opening Google…" : "Continue with Google"}</Text>
          </Pressable>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
            <View style={{ flex: 1, height: 1, backgroundColor: color.line }} />
            <Label>or with email</Label>
            <View style={{ flex: 1, height: 1, backgroundColor: color.line }} />
          </View>
          <View style={{ gap: 8 }}>
            <Label>Email address</Label>
            <TextInput
              value={email}
              onChangeText={setEmail}
              placeholder="you@domain.com"
              placeholderTextColor={color.faint}
              autoCapitalize="none"
              autoComplete="email"
              autoCorrect={false}
              keyboardType="email-address"
              textContentType="emailAddress"
              returnKeyType="go"
              onSubmitEditing={submit}
              style={{ height: 56, borderRadius: 28, paddingHorizontal: 22, backgroundColor: color.surface, color: color.white, fontFamily: font.sans, fontSize: 16, borderWidth: 1, borderColor: color.line }}
            />
          </View>
          <ErrorLine message={error} />
          <PillButton label="Email me a code" onPress={submit} busy={busy} />
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
