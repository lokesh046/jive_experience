import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { api } from "./api";

export function useUnread() {
  const [unread, setUnread] = useState(0);
  useFocusEffect(useCallback(() => {
    api<{ unread: number }>("notifications/unread").then((r) => setUnread(r.unread)).catch(() => {});
  }, []));
  return unread;
}
