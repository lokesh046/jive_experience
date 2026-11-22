import Image from "next/image";

/**
 * Local images go through next/image (AVIF/WebP, responsive sizes). Images from the
 * API can live on any host, so they use a plain lazy <img> until a media host is chosen.
 */
export function Photo({
  src, alt, sizes, priority = false, className,
}: { src: string; alt: string; sizes: string; priority?: boolean; className?: string }) {
  if (src.startsWith("/")) {
    return <Image src={src} alt={alt} fill sizes={sizes} priority={priority} className={className} />;
  }
  // Cloudinary resizes and picks AVIF/WebP at the edge, so ask for sizes, not the original.
  const cdn = src.startsWith("https://res.cloudinary.com/") && src.includes("/upload/");
  const at = (w: number) => src.replace("/upload/", `/upload/f_auto,q_auto,c_limit,w_${w}/`);
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={cdn ? at(800) : src} srcSet={cdn ? `${at(480)} 480w, ${at(800)} 800w, ${at(1280)} 1280w, ${at(1920)} 1920w` : undefined} sizes={cdn ? sizes : undefined} alt={alt} loading={priority ? "eager" : "lazy"} fetchPriority={priority ? "high" : undefined} decoding="async" className={className} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />;
}
