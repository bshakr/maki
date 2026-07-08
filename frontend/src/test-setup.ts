import "@testing-library/jest-dom/vitest";

// jsdom implements neither ResizeObserver nor Element.scrollIntoView, both of
// which cmdk (the command palette) touches on mount. Provide minimal stubs.
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// jsdom does not implement matchMedia, which the shadcn sidebar's
// useIsMobile hook relies on. Provide a minimal stub.
if (!window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}
