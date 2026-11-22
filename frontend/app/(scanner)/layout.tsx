/** The gate scanner is a tool, not a page of the public site: no site nav or footer. */
export default function ScannerLayout({ children }: { children: React.ReactNode }) {
  return <div className="sc-root">{children}</div>;
}
