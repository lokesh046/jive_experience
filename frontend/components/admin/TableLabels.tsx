"use client";
import { useEffect } from "react";

/**
 * On phones the admin tables stack each row, which drops the column headings. This copies each
 * heading onto its cell as `data-label`, so the stacked row can say what each value is. It follows
 * the page as tables load, filter or expand.
 */
export function TableLabels() {
  useEffect(() => {
    const root = document.querySelector(".ad-main");
    if (!root) return;
    const label = () => {
      root.querySelectorAll<HTMLElement>(".tbl").forEach((table) => {
        const head = table.querySelector<HTMLElement>(".tr.th");
        if (!head) return;
        const names = [...head.children].map((c) => (c.textContent ?? "").trim());
        table.querySelectorAll<HTMLElement>(".tr:not(.th)").forEach((row) => {
          [...row.children].forEach((cell, i) => {
            const name = names[i];
            if (name && cell.getAttribute("data-label") !== name) cell.setAttribute("data-label", name);
          });
        });
      });
    };
    label();
    const mo = new MutationObserver(label);
    mo.observe(root, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, []);
  return null;
}
