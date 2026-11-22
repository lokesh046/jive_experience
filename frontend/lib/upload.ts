import { ApiError, api } from "./api-client";

interface Signed {
  upload_url: string; api_key: string; timestamp: number; signature: string; folder: string; allowed_formats: string;
}
export const MAX_PHOTO_BYTES = 8 * 1024 * 1024;

/** Why a file cannot be uploaded, or null if it is fine. Checked before anything is sent. */
export function photoProblem(file: File): string | null {
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return "Use a JPG, PNG or WebP photo.";
  if (file.size > MAX_PHOTO_BYTES) return "That photo is over 8 MB. Choose a smaller one.";
  return null;
}

/** Uploads one photo straight to Cloudinary with a one-use signature from the API. Returns its URL. */
export async function uploadPhoto(file: File): Promise<string> {
  let s: Signed;
  try {
    s = await api<Signed>("/admin/uploads/sign", { method: "POST" });
  } catch (e) {
    throw new Error(e instanceof ApiError && e.status === 503 ? "Photo uploads are not set up yet." : "The upload did not go through. Please try again.");
  }
  const body = new FormData();
  body.append("file", file);
  body.append("api_key", s.api_key);
  body.append("timestamp", String(s.timestamp));
  body.append("signature", s.signature);
  body.append("folder", s.folder);
  body.append("allowed_formats", s.allowed_formats);
  const res = await fetch(s.upload_url, { method: "POST", body });
  if (!res.ok) throw new Error("The upload did not go through. Please try again.");
  return ((await res.json()) as { secure_url: string }).secure_url;
}
