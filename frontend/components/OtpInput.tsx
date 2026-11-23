"use client";
import { useRef } from "react";

/** Six single-digit boxes: type to advance, backspace to go back, paste a whole code. */
export function OtpInput({
  value, onChange, onComplete, invalid = false, disabled = false, length = 6,
}: { value: string; onChange: (v: string) => void; onComplete?: (v: string) => void; invalid?: boolean; disabled?: boolean; length?: number }) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const digits = Array.from({ length }, (_, i) => value[i] ?? "");

  function commit(next: string, focusAt: number) {
    const clean = next.replace(/\D/g, "").slice(0, length);
    onChange(clean);
    refs.current[Math.min(focusAt, length - 1)]?.focus();
    if (clean.length === length) onComplete?.(clean);
  }

  return (
    <div className={`otpx${invalid ? " bad" : ""}`} role="group" aria-label="Verification code">
      {digits.map((d, i) => (
        <input
          key={i}
          ref={(el) => { refs.current[i] = el; }}
          value={d}
          disabled={disabled}
          inputMode="numeric"
          pattern="\d*"
          autoComplete={i === 0 ? "one-time-code" : "off"}
          maxLength={length}
          aria-label={`Digit ${i + 1} of ${length}`}
          aria-invalid={invalid || undefined}
          onFocus={(e) => e.currentTarget.select()}
          onChange={(e) => {
            const typed = e.target.value.replace(/\D/g, "");
            if (!typed) return commit(value.slice(0, i) + value.slice(i + 1), i);
            // One digit replaces this box; several (paste, autofill) fill from here.
            commit(value.slice(0, i) + typed + value.slice(i + typed.length), i + typed.length);
          }}
          onKeyDown={(e) => {
            if (e.key === "Backspace" && !d && i > 0) { e.preventDefault(); commit(value.slice(0, i - 1), i - 1); }
            if (e.key === "ArrowLeft" && i > 0) refs.current[i - 1]?.focus();
            if (e.key === "ArrowRight" && i < length - 1) refs.current[i + 1]?.focus();
          }}
        />
      ))}
    </div>
  );
}
