import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;

const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export function MicIcon(p: P) {
  return (
    <svg viewBox="0 0 24 24" {...base} {...p}>
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" x2="12" y1="19" y2="22" />
    </svg>
  );
}

export function CheckIcon(p: P) {
  return (
    <svg viewBox="0 0 24 24" {...base} strokeWidth={2.25} {...p}>
      <path d="m5 12 5 5L20 7" />
    </svg>
  );
}

export function EndCallIcon(p: P) {
  return (
    <svg viewBox="0 0 24 24" {...base} {...p}>
      <path d="M3 12.5c5-4.5 13-4.5 18 0" />
      <path d="M5.5 10.5v3.2l-2.5-.6V11" />
      <path d="M18.5 10.5v3.2l2.5-.6V11" />
    </svg>
  );
}

export function RetryIcon(p: P) {
  return (
    <svg viewBox="0 0 24 24" {...base} {...p}>
      <path d="M20 12a8 8 0 1 1-2.3-5.7" />
      <path d="M20 4v5h-5" />
    </svg>
  );
}

export function InfoIcon(p: P) {
  return (
    <svg viewBox="0 0 24 24" {...base} {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </svg>
  );
}

export function WarnIcon(p: P) {
  return (
    <svg viewBox="0 0 24 24" {...base} {...p}>
      <path d="M12 3 2.5 19.5h19L12 3Z" />
      <path d="M12 10v4M12 17h.01" />
    </svg>
  );
}

export function CalendarIcon(p: P) {
  return (
    <svg viewBox="0 0 24 24" {...base} {...p}>
      <rect x="3.5" y="5" width="17" height="15" rx="2" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </svg>
  );
}

export function LinkIcon(p: P) {
  return (
    <svg viewBox="0 0 24 24" {...base} {...p}>
      <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.2 1.2" />
      <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.2-1.2" />
    </svg>
  );
}

export function KeyIcon(p: P) {
  return (
    <svg viewBox="0 0 24 24" {...base} {...p}>
      <circle cx="8" cy="14" r="4" />
      <path d="M11 11 20 2M15.5 6.5 18 9M18.5 3.5 21 6" />
    </svg>
  );
}

export function SendIcon(p: P) {
  return (
    <svg viewBox="0 0 24 24" {...base} {...p}>
      <path d="M4 12 20 4l-4 16-4-7-8-1Z" />
    </svg>
  );
}
