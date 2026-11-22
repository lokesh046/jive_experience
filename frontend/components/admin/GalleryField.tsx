"use client";
import { useId, useState } from "react";
import { photoProblem, uploadPhoto } from "@/lib/upload";

export const MAX_GALLERY = 10;
const thumb = (u: string) => u.replace("/upload/", "/upload/f_auto,q_auto,c_fill,w_240,h_160/");

/** Several photos for the event page slideshow: add many at once, reorder, remove. */
export function GalleryField({
  value, onChange, disabled,
}: { value: string[]; onChange: (urls: string[]) => void; disabled?: boolean }) {
  const id = useId();
  const [busy, setBusy] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const room = MAX_GALLERY - value.length;

  async function add(files: FileList | null) {
    if (!files?.length) return;
    setErr(null);
    const chosen = [...files].slice(0, Math.max(0, room));
    if (files.length > chosen.length) setErr(`Only ${MAX_GALLERY} photos fit in the slideshow.`);
    const problem = chosen.map(photoProblem).find(Boolean);
    if (problem) return setErr(problem);
    setBusy(chosen.length);
    const done: string[] = [];
    for (const file of chosen) {
      try { done.push(await uploadPhoto(file)); }
      catch (e) { setErr(e instanceof Error ? e.message : "The upload did not go through."); break; }
      finally { setBusy((n) => n - 1); }
    }
    setBusy(0);
    if (done.length) onChange([...value, ...done]);
  }
  const move = (i: number, d: number) => {
    const next = [...value]; const j = i + d;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };

  return (
    <div className="f wide">
      <label htmlFor={id}>Slideshow photos</label>
      {value.length > 0 && (
        <ul className="gal-edit">
          {value.map((u, i) => (
            <li key={u}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={thumb(u)} alt={`Photo ${i + 1}`} width={120} height={80} />
              {!disabled && (
                <span>
                  <button type="button" aria-label={`Move photo ${i + 1} earlier`} disabled={i === 0} onClick={() => move(i, -1)}>←</button>
                  <button type="button" aria-label={`Move photo ${i + 1} later`} disabled={i === value.length - 1} onClick={() => move(i, 1)}>→</button>
                  <button type="button" aria-label={`Remove photo ${i + 1}`} onClick={() => onChange(value.filter((x) => x !== u))}>×</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      <input id={id} type="file" multiple accept="image/jpeg,image/png,image/webp" disabled={disabled || busy > 0 || room <= 0} onChange={(e) => { void add(e.target.files); e.target.value = ""; }} />
      {busy > 0 && <span className="hint" role="status">Uploading {busy} photo{busy > 1 ? "s" : ""}…</span>}
      {err && <span className="err" role="alert">{err}</span>}
      {!err && <span className="hint">Choose several at once. They play after the banner photo, in this order. Up to {MAX_GALLERY}.</span>}
    </div>
  );
}
