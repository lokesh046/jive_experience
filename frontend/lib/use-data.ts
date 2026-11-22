"use client";
import { useEffect, useState } from "react";
import { api } from "./api-client";

/** Load a GET endpoint through the proxy. `reload()` fetches it again. Pass null to wait. */
export function useData<T>(path: string | null) {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({ data: null, error: null });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    let live = true;
    api<T>(path)
      .then((data) => live && setState({ data, error: null }))
      .catch((e: Error) => live && setState({ data: null, error: e.message }));
    return () => { live = false; };
  }, [path, tick]);
  return { data: state.data, error: state.error, loading: !!path && !state.data && !state.error, reload: () => setTick((t) => t + 1) };
}
