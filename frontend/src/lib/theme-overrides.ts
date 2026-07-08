import type { AppConfigResponse } from "@/api";

type Theme = AppConfigResponse["theme"];

function block(vars: Record<string, string>, selector: string): string {
  const decls = Object.entries(vars)
    .map(([token, value]) => `  --${token}: ${value};`)
    .join("\n");
  return decls ? `${selector} {\n${decls}\n}` : "";
}

// Build a stylesheet that overrides shadcn tokens from config.theme over the vanilla index.css
// defaults. Only listed tokens are emitted (`--<token>: <value>;`), scoped to :root (light) and
// .dark; everything else keeps its default. Returns "" when there's no theme / nothing to override.
export function themeOverrideCss(theme: Theme): string {
  if (!theme) return "";
  return [block(theme.light ?? {}, ":root"), block(theme.dark ?? {}, ".dark")]
    .filter(Boolean)
    .join("\n\n");
}
