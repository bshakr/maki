import { expect, test } from "vitest";

import { themeOverrideCss } from "@/lib/theme-overrides";

test("returns empty string when there is no theme", () => {
  expect(themeOverrideCss(null)).toBe("");
});

test("returns empty string when both modes are empty", () => {
  expect(themeOverrideCss({ light: {}, dark: {} })).toBe("");
});

test("emits only the provided tokens, prefixed and scoped per mode", () => {
  const css = themeOverrideCss({
    light: { primary: "oklch(0.5 0.2 280)", radius: "0.75rem" },
    dark: { primary: "oklch(0.6 0.2 280)" },
  });
  expect(css).toContain(":root {");
  expect(css).toContain("  --primary: oklch(0.5 0.2 280);");
  expect(css).toContain("  --radius: 0.75rem;");
  expect(css).toContain(".dark {");
  expect(css).toContain("  --primary: oklch(0.6 0.2 280);");
  // No token we didn't pass leaks in.
  expect(css).not.toContain("--background");
});

test("emits only the :root block when dark is absent", () => {
  const css = themeOverrideCss({ light: { ring: "oklch(0.5 0 0)" }, dark: {} });
  expect(css).toContain(":root {");
  expect(css).not.toContain(".dark {");
});
