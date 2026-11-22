import type { Metadata } from "next";
import { RequireRole } from "@/components/RequireRole";
import { Scanner } from "./Scanner";

export const metadata: Metadata = { title: "Scanner", robots: { index: false, follow: false } };

export default function Page() {
  return <RequireRole roles={["EVENT_STAFF", "ADMIN"]} next="/scan"><Scanner /></RequireRole>;
}
