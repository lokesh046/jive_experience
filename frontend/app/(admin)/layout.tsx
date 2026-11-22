import type { Metadata } from "next";
import { Suspense } from "react";
import { AdminShell } from "@/components/admin/AdminShell";

export const metadata: Metadata = { title: { default: "Admin", template: "%s — JIVE admin" }, robots: { index: false, follow: false } };

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  // The shell reads the current URL, which is only known per request, so it streams in.
  return (
    <Suspense fallback={<div className="wrap" style={{ padding: "96px 24px" }}><div className="skeleton" style={{ height: 48, maxWidth: 360 }} /></div>}>
      <AdminShell>{children}</AdminShell>
    </Suspense>
  );
}
