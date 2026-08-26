import { vi } from "vitest";

// Mock matchMedia for jsdom
globalThis.matchMedia = globalThis.matchMedia || vi.fn().mockImplementation((query) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: vi.fn(),
  removeListener: vi.fn(),
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  dispatchEvent: vi.fn(),
}));

// Mock localStorage
const store = {};
globalThis.localStorage = {
  getItem: (key) => store[key] || null,
  setItem: (key, value) => { store[key] = value.toString(); },
  removeItem: (key) => { delete store[key]; },
  clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
};

// Mock DataTransfer + DataTransferItem + DataTransferItemList (not available in jsdom)
if (typeof globalThis.DataTransfer === "undefined") {
  class MockDataTransferItemList {
    constructor() {
      this._items = [];
    }
    add(file) {
      this._items.push(file);
    }
    get length() {
      return this._items.length;
    }
  }
  class MockDataTransfer {
    constructor() {
      this.items = new MockDataTransferItemList();
    }
    get files() {
      return this.items._items;
    }
  }
  globalThis.DataTransfer = MockDataTransfer;
  window.DataTransfer = MockDataTransfer;
}

// Attach AzadToast to window for legacy tests
import AzadToast from "@app-static/js/components/toast.js";
window.AzadToast = AzadToast;
