"use client";
import { useId, useState } from "react";
import { ApiError, api } from "@/lib/api-client";

interface Signed {
  upload_url: string; api_key: string; timestamp: number; signature: string; folder: string; allowed_formats: string;
}
const MAX_BYTES = 8 * 1024 * 1024;

/** Uploads straight to Cloudinary with a one-use signature from the API. */
export function PhotoField({
  label, value, onChange, disabled, hint,
}: { label: string; value: string; onChange: (url: string) => void; disabled?: boolean; hint?: string }) {
  const id = useId();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function pick(file: File | undefined) {
    if (!file) return;
    setErr(null);
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return setErr("Use a JPG, PNG or WebP photo.");
    if (file.size > MAX_BYTES) return setErr("That photo is over 8 MB. Choose a smaller one.");
    setBusy(true);
    try {
      const s = await api<Signed>("/admin/uploads/sign", { method: "POST" });
      const body = new FormData();
      body.append("file", file);
      body.append("api_key", s.api_key);
      body.append("timestamp", String(s.timestamp));
      body.append("signature", s.signature);
      body.append("folder", s.folder);
      body.append("allowed_formats", s.allowed_formats);
      const res = await fetch(s.upload_url, { method: "POST", body });
      if (!res.ok) throw new Error("upload");
      const out = (await res.json()) as { secure_url: string };
      onChange(out.secure_url);
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 503 ? "Photo uploads are not set up yet." : "The upload did not go through. Please try again.");
    } finally {
      setBusy(false);
    }
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
