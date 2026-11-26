import { Ionicons } from "@expo/vector-icons";
import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";
import { Body, ErrorLine } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { inr } from "@/lib/format";
import type { EventDetail, PromoCheck, TicketCategoryPublic } from "@/lib/types";
import { color, font } from "@/theme";

export interface Pick { cat: TicketCategoryPublic | null; count: number; promo: PromoCheck | null; total: number }

/** Everything the picker and the bar under it share. */
export function usePicker(e: EventDetail | null) {
  const [catId, setCatId] = useState<string | null>(null);
  const [count, setCount] = useState(1);
  const [promo, setPromo] = useState<PromoCheck | null>(null);
  const [promoText, setPromoText] = useState("");
  const [promoBusy, setPromoBusy] = useState(false);
  const [promoErr, setPromoErr] = useState<string | null>(null);
  const cat = e?.ticket_categories.find((c) => c.id === catId) ?? null;

  const limit = (c: TicketCategoryPublic) => Math.max(1, Math.min(c.max_per_booking, c.available, e?.max_tickets_per_customer ?? 99));

  const check = useCallback(async (code: string, c: TicketCategoryPublic, qty: number, quiet = false) => {
    if (!e) return;
    setPromoBusy(true); if (!quiet) setPromoErr(null);
    try {
      setPromo(await api<PromoCheck>("bookings/promo-check", { method: "POST", json: { event_slug: e.slug, code, items: [{ ticket_category_id: c.id, quantity: qty }] } }));
      setPromoErr(null);
    } catch (x) {
      setPromo(null);
      setPromoErr(x instanceof ApiError ? x.message : "We could not check that code. Please try again.");
    } finally { setPromoBusy(false); }
  }, [e]);

  function choose(c: TicketCategoryPublic) {
    setCatId(c.id); setCount(Math.max(1, c.min_per_booking));
    if (promo) void check(promo.code, c, Math.max(1, c.min_per_booking), true);
  }
  function setQty(n: number) {
    if (!cat) return;
    const q = Math.min(limit(cat), Math.max(cat.min_per_booking, n));
    setCount(q);
    if (promo) void check(promo.code, cat, q, true);
  }
  const list = cat ? cat.price_paise * count : 0;
  const total = promo ? promo.total_paise : list;
  return { cat, count, promo, total, promoText, setPromoText, promoBusy, promoErr, choose, setQty, limit, check, removePromo: () => { setPromo(null); setPromoText(""); } };
}

export type PickerState = ReturnType<typeof usePicker>;

export function TicketPicker({ e, p }: { e: EventDetail; p: PickerState }) {
  const [promoOpen, setPromoOpen] = useState(false);
  return (
    <View style={{ gap: 10 }}>
      {e.ticket_categories.map((c) => {
        const on = p.cat?.id === c.id;
        return (
          <Pressable
            key={c.id}
            disabled={c.is_sold_out}
            onPress={() => p.choose(c)}
            accessibilityRole="radio"
            accessibilityState={{ selected: on, disabled: c.is_sold_out }}
            style={{ padding: 16, borderRadius: 20, backgroundColor: color.surface, borderWidth: on ? 2 : 1, borderColor: on ? color.white : color.line, opacity: c.is_sold_out ? 0.5 : 1, gap: 10 }}
          >
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <View style={{ flex: 1, paddingRight: 12, gap: 2 }}>
                <Text style={{ fontFamily: font.sansBold, fontSize: 16, color: color.white }}>{c.name}</Text>
                {!!c.description && <Text style={{ fontFamily: font.sans, fontSize: 13, color: color.muted }} numberOfLines={on ? 6 : 2}>{c.description}</Text>}
              </View>
              <Text style={{ fontFamily: font.serif, fontSize: 22, color: c.is_sold_out ? color.faint : color.white }}>{c.is_sold_out ? "Sold out" : inr(c.price_paise)}</Text>
            </View>
            {on && (
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                <Text style={{ fontFamily: font.sans, color: color.muted }}>Tickets</Text>
                <Stepper value={p.count} min={c.min_per_booking} max={p.limit(c)} onChange={p.setQty} />
              </View>
            )}
          </Pressable>
        );
      })}

      {p.cat && (
        p.promo ? (
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: 14, borderRadius: 16, backgroundColor: color.surface, borderWidth: 1, borderColor: color.line }}>
            <Text style={{ fontFamily: font.sansMedium, color: color.good, flex: 1 }}>{p.promo.description ?? "Promo code applied"} · {p.promo.code}</Text>
            <Pressable onPress={p.removePromo} accessibilityRole="button"><Text style={{ fontFamily: font.sansMedium, color: color.muted }}>Remove</Text></Pressable>
          </View>
        ) : promoOpen ? (
          <View style={{ gap: 8 }}>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <TextInput
                value={p.promoText}
                onChangeText={(t) => p.setPromoText(t.toUpperCase())}
                placeholder="Promo code" placeholderTextColor={color.faint}
                autoCapitalize="characters" autoCorrect={false} maxLength={40}
                style={{ flex: 1, height: 48, borderRadius: 24, paddingHorizontal: 18, backgroundColor: color.surface, color: color.white, fontFamily: font.sans, borderWidth: 1, borderColor: color.line }}
              />
              <Pressable
                disabled={p.promoBusy || !p.promoText.trim()}
                onPress={() => p.cat && p.check(p.promoText.trim(), p.cat, p.count)}
                accessibilityRole="button"
                style={{ height: 48, paddingHorizontal: 20, borderRadius: 24, backgroundColor: color.white, alignItems: "center", justifyContent: "center", opacity: p.promoBusy || !p.promoText.trim() ? 0.5 : 1 }}
              >
                {p.promoBusy ? <ActivityIndicator color={color.ink} /> : <Text style={{ fontFamily: font.sansBold, color: color.ink }}>Apply</Text>}
              </Pressable>
            </View>
            <ErrorLine message={p.promoErr} />
          </View>
        ) : (
          <Pressable onPress={() => setPromoOpen(true)} accessibilityRole="button"><Body style={{ textDecorationLine: "underline" }}>Have a promo code?</Body></Pressable>
        )
      )}
    </View>
  );
}

function Stepper({ value, min, max, onChange }: { value: number; min: number; max: number; onChange: (n: number) => void }) {
  const btn = (icon: "remove" | "add", off: boolean, to: number, label: string) => (
    <Pressable onPress={() => onChange(to)} disabled={off} accessibilityRole="button" accessibilityLabel={label} hitSlop={8}
      style={{ width: 40, height: 40, borderRadius: 20, borderWidth: 1, borderColor: color.line, alignItems: "center", justifyContent: "center", opacity: off ? 0.35 : 1 }}>
      <Ionicons name={icon} size={20} color={color.white} />
    </Pressable>
  );
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 14 }}>
      {btn("remove", value <= min, value - 1, "One fewer ticket")}
      <Text accessibilityLiveRegion="polite" style={{ fontFamily: font.serif, fontSize: 24, color: color.white, minWidth: 24, textAlign: "center" }}>{value}</Text>
      {btn("add", value >= max, value + 1, "One more ticket")}
    </View>
  );
}
