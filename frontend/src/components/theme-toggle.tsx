import { Monitor, Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTheme, type Theme } from "@/components/theme-provider";

// Single-click cycle: light → dark → system → light. The icon shows the current
// preference (Monitor for system), so there's no hidden menu to open.
const NEXT: Record<Theme, Theme> = {
  light: "dark",
  dark: "system",
  system: "light",
};

const ICON = {
  light: Sun,
  dark: Moon,
  system: Monitor,
} as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const Icon = ICON[theme];

  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-8"
      onClick={() => setTheme(NEXT[theme])}
      aria-label={`Theme: ${theme}. Click to switch.`}
      title={`Theme: ${theme} (click to cycle)`}
    >
      <Icon className="size-4" />
    </Button>
  );
}
