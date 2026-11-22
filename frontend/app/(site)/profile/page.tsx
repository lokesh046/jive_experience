import type { Metadata } from "next";
import { ProfileForm } from "./ProfileForm";

export const metadata: Metadata = { title: "Profile", robots: { index: false, follow: false } };

export default function Page() {
  return <ProfileForm />;
}
