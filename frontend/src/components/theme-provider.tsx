import { createContext, useContext, useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";

type ThemeProviderProps = {
  children: React.ReactNode;
  defaultTheme?: Theme;
  storageKey?: string;
};

type ThemeProviderState = {
  /** The user's selected preference: "light", "dark", or "system". */
  theme: Theme;
  /** Persists the preference and applies it. */
  setTheme: (theme: Theme) => void;
  /** The concrete theme currently on screen ("light" | "dark"), with "system" resolved. */
  resolvedTheme: "light" | "dark";
};

const initialState: ThemeProviderState = {
  theme: "system",
  setTheme: () => null,
  resolvedTheme: "light",
};

const ThemeProviderContext = createContext<ThemeProviderState>(initialState);

const DARK_QUERY = "(prefers-color-scheme: dark)";

function systemTheme(): "light" | "dark" {
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

/** Toggle the `dark` class on <html>; returns the concrete theme that was applied. */
function applyTheme(theme: Theme): "light" | "dark" {
  const resolved = theme === "system" ? systemTheme() : theme;
  const root = window.document.documentElement;
  root.classList.toggle("dark", resolved === "dark");
  return resolved;
}

export function ThemeProvider({
  children,
  defaultTheme = "system",
  storageKey = "app-ui-theme",
}: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(
    () => (localStorage.getItem(storageKey) as Theme | null) ?? defaultTheme,
  );
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(() =>
    theme === "system" ? systemTheme() : theme,
  );

  // Apply the class whenever the preference changes.
  useEffect(() => {
    setResolvedTheme(applyTheme(theme));
  }, [theme]);

  // While in "system" mode, follow live OS changes.
  useEffect(() => {
    if (theme !== "system") return;
    const mql = window.matchMedia(DARK_QUERY);
    const onChange = () => setResolvedTheme(applyTheme("system"));
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [theme]);

  const value: ThemeProviderState = {
    theme,
    resolvedTheme,
    setTheme: (next: Theme) => {
      localStorage.setItem(storageKey, next);
      setThemeState(next);
    },
  };

  return (
    <ThemeProviderContext.Provider value={value}>
      {children}
    </ThemeProviderContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeProviderContext);
  if (context === undefined) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}
