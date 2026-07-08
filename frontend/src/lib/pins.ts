import { useSyncExternalStore } from "react";

// ─────────────────────────────────────────────────────────────────────────────
// PINS — a localStorage-backed list of pinned service names. This is a personal
// preference on a local single-user tool, so there is no backend: the source of
// truth is one localStorage key, surfaced to React via useSyncExternalStore so
// every consumer re-renders together and edits in another tab sync via the
// `storage` event. Dependency-free on purpose (no zustand etc.).
// ─────────────────────────────────────────────────────────────────────────────

export const PINS_STORAGE_KEY = "maki:pinned-services";

// An immutable snapshot getSnapshot can return by reference. We only allocate a
// new array when the persisted value actually changes, so React's
// useSyncExternalStore sees a stable identity between unrelated renders.
let snapshot: string[] = readFromStorage();

const listeners = new Set<() => void>();

function readFromStorage(): string[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = localStorage.getItem(PINS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Keep only non-empty strings, de-duplicated, preserving order.
    const seen = new Set<string>();
    const out: string[] = [];
    for (const v of parsed) {
      if (typeof v === "string" && v && !seen.has(v)) {
        seen.add(v);
        out.push(v);
      }
    }
    return out;
  } catch {
    // Corrupt JSON (or storage access denied) → behave as "no pins".
    return [];
  }
}

function emit() {
  for (const listener of listeners) listener();
}

// Persist + refresh the in-memory snapshot, then notify subscribers. Skips the
// write+emit when nothing changed so we don't churn renders.
function setPins(next: string[]) {
  const changed =
    next.length !== snapshot.length ||
    next.some((name, i) => name !== snapshot[i]);
  if (!changed) return;
  snapshot = next;
  try {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(PINS_STORAGE_KEY, JSON.stringify(next));
    }
  } catch {
    // Storage may be unavailable (private mode, quota). The in-memory snapshot
    // still updates so the UI stays responsive for this session.
  }
  emit();
}

export function getPins(): string[] {
  return snapshot;
}

export function isPinned(name: string): boolean {
  return snapshot.includes(name);
}

export function pin(name: string) {
  if (!name || snapshot.includes(name)) return;
  setPins([...snapshot, name]);
}

export function unpin(name: string) {
  if (!snapshot.includes(name)) return;
  setPins(snapshot.filter((n) => n !== name));
}

export function toggle(name: string) {
  if (snapshot.includes(name)) unpin(name);
  else pin(name);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

// Cross-tab sync: another tab writing the key fires a `storage` event here. We
// re-read and emit so this tab's React tree catches up.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key !== null && e.key !== PINS_STORAGE_KEY) return;
    const next = readFromStorage();
    const changed =
      next.length !== snapshot.length ||
      next.some((name, i) => name !== snapshot[i]);
    if (changed) {
      snapshot = next;
      emit();
    }
  });
}

export type UsePinsResult = {
  pins: string[];
  isPinned: (name: string) => boolean;
  toggle: (name: string) => void;
  pin: (name: string) => void;
  unpin: (name: string) => void;
};

export function usePins(): UsePinsResult {
  const pins = useSyncExternalStore(subscribe, getPins, getPins);
  return {
    pins,
    isPinned: (name) => pins.includes(name),
    toggle,
    pin,
    unpin,
  };
}
