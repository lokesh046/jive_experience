import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
        <a className="skip" href="#main">Skip to content</a>
      <SiteHeader />
      <div id="main" style={{ flex: 1, display: "flex", flexDirection: "column" }}>{children}</div>
      <SiteFooter />
    </>
  );
}
