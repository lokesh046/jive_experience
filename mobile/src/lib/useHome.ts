import { useEffect, useState } from "react";
import { api } from "./api";
import { ARCHIVE, ARTISTS } from "./content";
import type { EventDetail, EventListItem } from "./types";

export interface HomeArtist { name: string; note: string; img: string }
export interface HomeArchive { img: string; caption: string }

/** The artists an admin picked; else performers from event lineups; else the placeholders, so it is never bare. */
export function useHomeExtras(events: EventListItem[] | null) {
  const [artists, setArtists] = useState<HomeArtist[]>(ARTISTS);
  const [archive, setArchive] = useState<HomeArchive[]>(ARCHIVE);

  useEffect(() => {
    api<{ caption: string | null; photo_url: string }[]>("archive")
      .then((rows) => rows.length && setArchive(rows.map((r) => ({ img: r.photo_url, caption: r.caption ?? "" }))))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!events) return;
    let live = true;
    (async () => {
      try {
        const rows = await api<{ name: string; note: string | null; photo_url: string | null }[]>("artists");
        const chosen = rows.filter((a) => a.photo_url).map((a) => ({ name: a.name, note: a.note ?? "", img: a.photo_url as string }));
        if (chosen.length) return live && setArtists(chosen);
      } catch {}
      try {
        const details = await Promise.all(events.slice(0, 8).map((e) => api<EventDetail>(`events/${e.slug}`).catch(() => null)));
        const seen = new Set<string>(); const out: HomeArtist[] = [];
        for (const d of details) for (const p of d?.lineup ?? []) {
          const k = p.name.trim().toLowerCase();
          if (!p.photo_url || seen.has(k)) continue;
          seen.add(k); out.push({ name: p.name, note: p.role ?? "", img: p.photo_url });
        }
        if (out.length && live) setArtists(out.slice(0, 8));
      } catch {}
    })();
    return () => { live = false; };
  }, [events]);

  return { artists, archive };
}
