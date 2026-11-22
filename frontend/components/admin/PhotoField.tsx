"use client";
import { useId, useState } from "react";
import { photoProblem, uploadPhoto } from "@/lib/upload";

/** One photo, uploaded straight to Cloudinary. */
export function PhotoField({
  label, value, onChange, disabled, hint,
}: { label: string; value: string; onChange: (url: string) => void; disabled?: boolean; hint?: string }) {
  const id = useId();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function pick(file: File | undefined) {
    if (!file) return;
    setErr(null);
    const bad = photoProblem(file);
    if (bad) return setErr(bad);
    setBusy(true);
    try { onChange(await uploadPhoto(file)); }
    catch (e) { setErr(e instanceof Error ? e.message : "The upload did not go through."); }
    finally { setBusy(false); }
  }

  return (
    <div className="f wide">
      <label htmlFor={id}>{label}</label>
      {value && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={value.replace("/upload/", "/upload/f_auto,q_auto,w_480/")} alt="" width={240} style={{ borderRadius: 12, maxWidth: "100%", height: "auto", marginBottom: 8 }} />
      )}
      <input id={id} type="file" accept="image/jpeg,image/png,image/webp" disabled={disabled || busy} onChange={(e) => { void pick(e.target.files?.[0]); e.target.value = ""; }} />
      {busy && <span className="hint" role="status">Uploading…</span>}
      {err && <span className="err" role="alert">{err}</span>}
      {hint && !err && <span className="hint">{hint}</span>}
      {value && !disabled && <button type="button" className="link" onClick={() => onChange("")}>Remove photo</button>}
    </div>
  );
}
