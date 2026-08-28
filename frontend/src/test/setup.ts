import "@testing-library/jest-dom/vitest";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }),
});

if (!("text" in File.prototype)) {
  Object.defineProperty(File.prototype, "text", {
    configurable: true,
    value(this: File) {
      return new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result ?? ""));
        reader.onerror = () => reject(reader.error ?? new Error("Unable to read test file"));
        reader.readAsText(this);
      });
    },
  });
}

if (!("zoom" in CSSStyleDeclaration.prototype)) {
  Object.defineProperty(CSSStyleDeclaration.prototype, "zoom", {
    configurable: true,
    get(this: CSSStyleDeclaration) {
      return this.getPropertyValue("zoom");
    },
    set(this: CSSStyleDeclaration, value: string) {
      this.setProperty("zoom", value);
    },
  });
}
