/** A user's photo. Uploaded photos come back as a relative API path; Google's are absolute URLs. */
export function avatarSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.startsWith("/") ? `/api${url}` : url;
}

export function Avatar({ url, size }: { url: string | null | undefined; size?: number }) {
  const src = avatarSrc(url);
  return (
    <span className="pic" style={size ? { width: size, height: size } : undefined}>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt="" referrerPolicy="no-referrer" />
      ) : (
        <svg width="40%" height="40%" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="8" r="4" /><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7" />
        </svg>
      )}
    </span>
  );
}
