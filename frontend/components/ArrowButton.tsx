import Link from "next/link";
import type { ComponentPropsWithoutRef } from "react";

/**
 * A pill with an arrow disc on its right. On hover the disc grows to fill the pill and the label
 * turns light. Renders a link when given `href`, otherwise a button. Styles live in globals.css (.pill.go).
 */
type Common = { children: React.ReactNode; full?: boolean; className?: string };
type AsLink = Common & { href: string } & Omit<ComponentPropsWithoutRef<typeof Link>, "href" | "className" | "children">;
type AsButton = Common & { href?: undefined } & Omit<ComponentPropsWithoutRef<"button">, "className" | "children">;

const Arrow = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
);

export function ArrowButton(props: AsLink | AsButton) {
  const { children, full, className = "", ...rest } = props;
  const cls = `pill go${full ? " full" : ""}${className ? ` ${className}` : ""}`;
  const inner = (<><span className="go-t">{children}</span><span className="go-a"><Arrow /></span></>);
  if ("href" in rest && rest.href !== undefined) {
    const { href, ...linkProps } = rest as Omit<AsLink, keyof Common>;
    return <Link className={cls} href={href} {...linkProps}>{inner}</Link>;
  }
  const { type = "button", ...btn } = rest as Omit<AsButton, keyof Common>;
  return <button className={cls} type={type} {...btn}>{inner}</button>;
}
