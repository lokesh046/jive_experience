import type React from "react";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Body, ErrorLine, H1 } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { color, font } from "@/theme";

const LEN = 6;

export default function Code() {
  const { email } = useLocalSearchParams<{ email: string }>();
  const { verifyCode, requestCode } = useAuth();
  const router = useRouter();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wait, setWait] = useState(60);
  const input = useRef<React.ComponentRef<typeof TextInput>>(null);

  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  async function submit(value: string) {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      await verifyCode(email, value);   // the root gate moves us on once signed in
    } catch (err: any) {
      setError(err?.message ?? "That code did not work.");
      setCode("");
      input.current?.focus();
    } finally { setBusy(false); }
  }

  function change(text: string) {
    const digits = text.replace(/\D/g, "").slice(0, LEN);
    setCode(digits);
    if (digits.length === LEN) submit(digits);
  }

  async function resend() {
    setError(null);
    try { await requestCode(email); setWait(60); } catch (err: any) { setError(err?.message ?? "Could not resend."); }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={{ padding: 24, gap: 20, flexGrow: 1, justifyContent: "center" }} keyboardShouldPersistTaps="handled">
          <H1>Check your email</H1>
          <Body>We sent a code to <Text style={{ color: color.white }}>{email}</Text>. It lasts 10 minutes.</Body>

          <Pressable onPress={() => input.current?.focus()} accessibilityLabel="Six digit code" style={{ flexDirection: "row", gap: 10, marginVertical: 12 }}>
            {Array.from({ length: LEN }).map((_, i) => {
              const filled = i < code.length;
              const active = i === Math.min(code.length, LEN - 1);
              return (
                <View key={i} style={{ flex: 1, height: 60, borderRadius: 16, alignItems: "center", justifyContent: "center", backgroundColor: color.surface, borderWidth: 1, borderColor: active ? color.white : color.line }}>
                  <Text style={{ fontFamily: font.serif, fontSize: 28, color: color.white }}>{filled ? code[i] : ""}</Text>
                </View>
              );
            })}
            <TextInput
              ref={input}
              value={code}
              onChangeText={change}
              autoFocus
              keyboardType="number-pad"
              textContentType="oneTimeCode"
              autoComplete="one-time-code"
              maxLength={LEN}
              caretHidden
              style={{ position: "absolute", opacity: 0.01, width: "100%", height: 60 }}
            />
          </Pressable>

          <ErrorLine message={error} />
          <Pressable onPress={resend} disabled={wait > 0 || busy} accessibilityRole="button">
            <Text style={{ fontFamily: font.sansMedium, color: wait > 0 ? color.faint : color.white }}>{wait > 0 ? `Send a new code in ${wait}s` : "Send a new code"}</Text>
          </Pressable>
          <Pressable onPress={() => router.back()} accessibilityRole="button">
            <Text style={{ fontFamily: font.sansMedium, color: color.muted }}>Change email</Text>
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
