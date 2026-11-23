import type { Metadata } from "next";
import { RequireRole } from "@/components/RequireRole";
import { BoxOffice } from "./BoxOffice";

export const metadata: Metadata = { title: "Box office", robots: { index: false, follow: false } };

export default function Page() {
  return <RequireRole roles={["EVENT_STAFF", "ADMIN"]} next="/box-office"><BoxOffice /></RequireRole>;
}
