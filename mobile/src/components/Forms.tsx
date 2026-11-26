import { useState } from "react";
import { Text, TextInput, View, type TextInputProps } from "react-native";
import { Body, ErrorLine, H2, Label, PillButton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { color, font } from "@/theme";

const field = { height: 52, borderRadius: 26, paddingHorizontal: 20, backgroundColor: color.surface, color: color.white, fontFamily: font.sans, fontSize: 16, borderWidth: 1, borderColor: color.line } as const;

function Field({ label, ...p }: TextInputProps & { label: string }) {
  return (
    <View style={{ gap: 6 }}>
      <Label>{label}</Label>
      <TextInput placeholderTextColor={color.faint} accessibilityLabel={label} {...p} style={[field, p.multiline && { height: 120, paddingTop: 14, borderRadius: 24, textAlignVertical: "top" }]} />
    </View>
  );
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const reason = (e: unknown) => (e instanceof ApiError && e.status === 429 ? "Too many requests from this connection. Please try again later." : e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

/** Private booking enquiry, the same as the website's. */
export function EnquiryForm() {
  const [v, set] = useState({ name: "", email: "", phone: "", date: "", guests: "", message: "" });
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const up = (k: keyof typeof v) => (t: string) => setV(k, t);
  const setV = (k: keyof typeof v, t: string) => set((s) => ({ ...s, [k]: t }));

  async function submit() {
    if (!v.name.trim()) return setErr("Tell us your name.");
    if (!EMAIL.test(v.email.trim())) return setErr("Enter a valid email address.");
    if (v.message.trim().length < 10) return setErr("Tell us a little more about what you are planning.");
    if (v.date && !/^\d{4}-\d{2}-\d{2}$/.test(v.date)) return setErr("Write the date as YYYY-MM-DD, or leave it empty.");
    setBusy(true); setErr(null);
    try {
      await api("enquiries", { method: "POST", json: { name: v.name.trim(), email: v.email.trim(), phone: v.phone.trim() || null, event_date: v.date || null, guests: v.guests ? Number(v.guests) : null, message: v.message.trim(), website: "" } });
      setDone(true);
    } catch (e) { setErr(reason(e)); } finally { setBusy(false); }
  }

  if (done) return <Body style={{ color: color.good }}>Thank you. We have your enquiry and will reply by email soon.</Body>;
  return (
    <View style={{ gap: 12 }}>
      <Field label="Your name" value={v.name} onChangeText={up("name")} autoComplete="name" maxLength={120} placeholder="Priya Nair" />
      <Field label="Email" value={v.email} onChangeText={up("email")} keyboardType="email-address" autoCapitalize="none" autoComplete="email" placeholder="you@example.com" />
      <Field label="Phone (optional)" value={v.phone} onChangeText={up("phone")} keyboardType="phone-pad" maxLength={30} placeholder="+91" />
      <View style={{ flexDirection: "row", gap: 10 }}>
        <View style={{ flex: 1 }}><Field label="Date (optional)" value={v.date} onChangeText={up("date")} placeholder="YYYY-MM-DD" maxLength={10} /></View>
        <View style={{ flex: 1 }}><Field label="Guests (optional)" value={v.guests} onChangeText={(t) => setV("guests", t.replace(/\D/g, ""))} keyboardType="number-pad" maxLength={4} placeholder="40" /></View>
      </View>
      <Field label="What are you planning?" value={v.message} onChangeText={up("message")} multiline maxLength={2000} placeholder="A private listening evening for 40 guests…" />
      <ErrorLine message={err} />
      <PillButton label="Send enquiry" onPress={submit} busy={busy} />
    </View>
  );
}

/** Join the waitlist for a sold-out event. */
export function WaitlistForm({ slug, categories }: { slug: string; categories: { id: string; name: string }[] }) {
  const [email, setEmail] = useState("");
  const [qty, setQty] = useState("1");
  const [cat, setCat] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    if (!EMAIL.test(email.trim())) return setErr("Enter a valid email address.");
    setBusy(true); setErr(null);
    try {
      await api(`events/${slug}/waitlist`, { method: "POST", json: { email: email.trim(), quantity: Math.max(1, Number(qty) || 1), ticket_category_id: cat, website: "" } });
      setDone(true);
    } catch (e) { setErr(reason(e)); } finally { setBusy(false); }
  }

  if (done) return <Body style={{ color: color.good }}>You are on the list. We will email you if tickets come back.</Body>;
  return (
    <View style={{ gap: 12 }}>
      <Body>Sold out. Leave your email and we will tell you if tickets come back.</Body>
      <Field label="Email" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" autoComplete="email" placeholder="you@example.com" />
      <Field label="Tickets" value={qty} onChangeText={(t) => setQty(t.replace(/\D/g, ""))} keyboardType="number-pad" maxLength={2} />
      {categories.length > 1 && (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
          {[{ id: null as string | null, name: "Any" }, ...categories].map((c) => (
            <Text key={c.id ?? "any"} onPress={() => setCat(c.id)} accessibilityRole="button" style={{ fontFamily: font.sansMedium, color: cat === c.id ? color.ink : color.white, backgroundColor: cat === c.id ? color.white : "transparent", borderWidth: 1, borderColor: color.line, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 8, overflow: "hidden" }}>{c.name}</Text>
          ))}
        </View>
      )}
      <ErrorLine message={err} />
      <PillButton label="Join the waitlist" onPress={submit} busy={busy} />
    </View>
  );
}

export function NewsletterSignup() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function submit() {
    if (!EMAIL.test(email.trim())) return setErr("Enter a valid email address.");
    setBusy(true); setErr(null);
    try { await api("newsletter/subscribe", { method: "POST", json: { email: email.trim(), website: "" } }); setDone(true); }
    catch (e) { setErr(reason(e)); } finally { setBusy(false); }
  }
  if (done) return <Body style={{ color: color.good }}>You are subscribed. See you at the next one.</Body>;
  return (
    <View style={{ gap: 12 }}>
      <H2>Stay in the loop</H2>
      <Body>New nights, announced here first.</Body>
      <Field label="Email" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" autoComplete="email" placeholder="you@example.com" />
      <ErrorLine message={err} />
      <PillButton label="Subscribe" onPress={submit} busy={busy} />
    </View>
  );
}
