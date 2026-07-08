import type { SVGProps } from "react";

/**
 * Neutral app mark (icon only). Uses `currentColor` so it inherits the theme — a deployment can
 * brand it via CSS/theme rather than a hardcoded fill.
 */
export function MarkLogo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      width="32"
      height="32"
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Logo"
      {...props}
    >
      <rect x="5" y="5" width="22" height="22" rx="6" fill="currentColor" />
      <rect x="12" y="12" width="8" height="8" rx="2" fill="var(--background)" />
    </svg>
  );
}
