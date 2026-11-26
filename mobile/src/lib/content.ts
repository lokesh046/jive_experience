import { site } from "./images";

// Shown when the admin has not added real artists, archive photos or services yet, as on the website.
export const ARTISTS = [
  { name: "Anyasa", note: "Modular synthesizers and acoustic string arrangements", img: site("artist-anyasa") },
  { name: "Kohra", note: "Deep hypnotic soundscapes and resonant sub-harmonics", img: site("artist-kohra") },
  { name: "Blot!", note: "Analogue tape loops, spatial delays and live electronics", img: site("artist-blot") },
  { name: "Komorebi", note: "Solo violoncello, vocal textures and ambient modular", img: site("artist-komorebi") },
];

export const ARCHIVE = [
  { caption: "Bandra Vinyl Salon, March 2027", img: site("archive-vinyl") },
  { caption: "Resonance in ruin, November 2026", img: site("archive-vault") },
  { caption: "Sub-sonic warehouse, January 2027", img: site("archive-warehouse") },
];

export const PRIVATE_SERVICES = [
  { name: "Private listening sessions", note: "Acoustic calibration, low lighting and a resident artist for an intimate evening." },
  { name: "Table reservations", note: "Reserved seating and dedicated service for your group on event nights." },
  { name: "Brand showcases", note: "A considered setting for launches, previews and press evenings." },
  { name: "Artist productions", note: "Production support for touring and resident artists." },
];
