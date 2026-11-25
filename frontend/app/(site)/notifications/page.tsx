import type { Metadata } from "next";
import { Notifications } from "./Notifications";

export const metadata: Metadata = { title: "Notifications", robots: { index: false, follow: false } };

export default function Page() {
  return <Notifications />;
}
