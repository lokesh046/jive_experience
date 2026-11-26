import { Modal, Pressable, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { WebView } from "react-native-webview";
import { color, font } from "@/theme";

export interface PayResult { razorpay_payment_id: string; razorpay_order_id: string; razorpay_signature: string }

/** Razorpay's checkout in a full-screen sheet. `html` is null while closed. */
export function RazorpaySheet({ html, onSuccess, onFailed, onClose }: {
  html: string | null; onSuccess: (r: PayResult) => void; onFailed: () => void; onClose: () => void;
}) {
  function onMessage(raw: string) {
    let m: any; try { m = JSON.parse(raw); } catch { return; }
    if (m.type === "success") onSuccess(m.payload);
    else if (m.type === "failed") onFailed();
    else onClose();
  }
  return (
    <Modal visible={html !== null} animationType="slide" onRequestClose={onClose}>
      <SafeAreaView style={{ flex: 1, backgroundColor: color.bg }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between", paddingHorizontal: 20, paddingVertical: 12 }}>
          <Text style={{ fontFamily: font.sansBold, color: color.white }}>Payment</Text>
          <Pressable onPress={onClose} accessibilityRole="button" hitSlop={10}><Text style={{ fontFamily: font.sansMedium, color: color.muted }}>Close</Text></Pressable>
        </View>
        {html && (
          <WebView originWhitelist={["*"]} source={{ html, baseUrl: "https://checkout.razorpay.com" }} onMessage={(e) => onMessage(e.nativeEvent.data)}
            javaScriptEnabled domStorageEnabled setSupportMultipleWindows={false} style={{ flex: 1, backgroundColor: color.bg }} />
        )}
      </SafeAreaView>
    </Modal>
  );
}
