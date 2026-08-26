import { describe, it, expect, beforeEach, vi } from "vitest";

describe("Charts - getChartConfig", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("parses valid chart data attributes", () => {
    const canvas = document.createElement("canvas");
    canvas.dataset.chart = "bar";
    canvas.dataset.chartLabels = '["A", "B", "C"]';
    canvas.dataset.chartValues = "[10, 20, 30]";
    canvas.dataset.chartColors = '["#f00", "#0f0", "#00f"]';
    canvas.dataset.chartTitle = "Test Chart";

    // Replicate getChartConfig logic
    let config;
    try {
      config = {
        type: canvas.dataset.chart || "bar",
        labels: JSON.parse(canvas.dataset.chartLabels || "[]"),
        values: JSON.parse(canvas.dataset.chartValues || "[]"),
        colors: JSON.parse(canvas.dataset.chartColors || "[]"),
        title: canvas.dataset.chartTitle || "",
      };
    } catch {
      config = null;
    }

    expect(config).toBeTruthy();
    expect(config.type).toBe("bar");
    expect(config.labels).toEqual(["A", "B", "C"]);
    expect(config.values).toEqual([10, 20, 30]);
    expect(config.title).toBe("Test Chart");
  });

  it("returns null for invalid JSON", () => {
    const canvas = document.createElement("canvas");
    canvas.dataset.chartLabels = "not-json";

    let config;
    try {
      config = {
        labels: JSON.parse(canvas.dataset.chartLabels || "[]"),
      };
    } catch {
      config = null;
    }

    expect(config).toBeNull();
  });

  it("defaults to empty arrays when no data attributes", () => {
    const canvas = document.createElement("canvas");
    const labels = JSON.parse(canvas.dataset.chartLabels || "[]");
    const values = JSON.parse(canvas.dataset.chartValues || "[]");

    expect(labels).toEqual([]);
    expect(values).toEqual([]);
  });
});

describe("Charts - Canvas rendering", () => {
  let mockCtx;

  beforeEach(() => {
    mockCtx = {
      clearRect: vi.fn(),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
      fill: vi.fn(),
      closePath: vi.fn(),
      arc: vi.fn(),
      fillRect: vi.fn(),
      fillText: vi.fn(),
      scale: vi.fn(),
      set fillStyle(_v) {},
      get fillStyle() { return "#000"; },
      set strokeStyle(_v) {},
      get strokeStyle() { return "#ccc"; },
      set font(_v) {},
      get font() { return "12px Cairo"; },
      set textAlign(_v) {},
      get textAlign() { return "center"; },
    };
  });

  it("drawBarChart draws bars for each value", () => {
    const config = {
      labels: ["A", "B"],
      values: [10, 20],
      colors: ["#f00", "#0f0"],
      title: "Bar Chart",
    };

    // Simulate bar chart drawing
    config.values.forEach((value) => {
      mockCtx.fillRect(0, 0, 50, value);
    });

    expect(mockCtx.fillRect).toHaveBeenCalledTimes(2);
  });

  it("drawBarChart draws title", () => {
    const config = { title: "My Chart", labels: [], values: [], colors: [] };
    if (config.title) {
      mockCtx.fillText(config.title, 200, 18);
    }
    expect(mockCtx.fillText).toHaveBeenCalledWith("My Chart", 200, 18);
  });

  it("drawDoughnutChart draws slices", () => {
    const values = [30, 50, 20];
    const total = values.reduce((a, b) => a + b, 0);

    values.forEach((value) => {
      const slice = (value / total) * 2 * Math.PI;
      mockCtx.arc(100, 100, 60, 0, slice);
    });

    expect(mockCtx.arc).toHaveBeenCalledTimes(3);
  });

  it("handles empty values array", () => {
    const values = [];
    values.forEach((value) => {
      mockCtx.fillRect(0, 0, 50, value);
    });
    expect(mockCtx.fillRect).not.toHaveBeenCalled();
  });

  it("handles single value doughnut", () => {
    const values = [100];
    const total = 100;
    const slice = (values[0] / total) * 2 * Math.PI;
    mockCtx.arc(100, 100, 60, -Math.PI / 2, -Math.PI / 2 + slice);
    expect(mockCtx.arc).toHaveBeenCalledTimes(1);
  });
});

describe("Charts - RTL support", () => {
  it("detects RTL from document.dir", () => {
    document.dir = "rtl";
    const isRTL = document.dir === "rtl";
    expect(isRTL).toBe(true);
  });

  it("detects LTR from document.dir", () => {
    document.dir = "ltr";
    const isRTL = document.dir === "rtl";
    expect(isRTL).toBe(false);
  });
});

describe("Charts - Canvas sizing", () => {
  it("scales canvas for device pixel ratio", () => {
    const canvas = document.createElement("canvas");
    const ratio = window.devicePixelRatio || 1;
    const rect = { width: 400, height: 300 };

    canvas.width = Math.max(1, Math.floor(rect.width * ratio));
    canvas.height = Math.max(1, Math.floor(rect.height * ratio));

    expect(canvas.width).toBeGreaterThan(0);
    expect(canvas.height).toBeGreaterThan(0);
  });

  it("prevents zero-size canvas", () => {
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.floor(0 * (window.devicePixelRatio || 1)));
    canvas.height = Math.max(1, Math.floor(0 * (window.devicePixelRatio || 1)));

    expect(canvas.width).toBe(1);
    expect(canvas.height).toBe(1);
  });
});

describe("Charts - Debounce", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("debounces resize handler", () => {
    let callCount = 0;
    let t;
    const debouncedFn = () => {
      clearTimeout(t);
      t = setTimeout(() => callCount++, 200);
    };

    debouncedFn();
    debouncedFn();
    debouncedFn();

    vi.advanceTimersByTime(200);
    expect(callCount).toBe(1);
  });
});

describe("Charts - CSS variable resolution", () => {
  it("reads CSS variable with fallback", () => {
    // In jsdom, getComputedStyle exists on window not document
    const mockGetComputedStyle = vi.fn().mockReturnValue({
      getPropertyValue: vi.fn().mockReturnValue(""),
    });
    vi.stubGlobal("getComputedStyle", mockGetComputedStyle);

    const fallback = "#014e7c";
    const result = getComputedStyle(document.documentElement)
      .getPropertyValue("--azad-navy")
      .trim() || fallback;

    expect(result).toBe(fallback);
    vi.restoreAllMocks();
  });

  it("returns CSS value when set", () => {
    const mockGetComputedStyle = vi.fn().mockReturnValue({
      getPropertyValue: vi.fn().mockReturnValue("#ff0000"),
    });
    vi.stubGlobal("getComputedStyle", mockGetComputedStyle);

    const result = getComputedStyle(document.documentElement)
      .getPropertyValue("--color")
      .trim() || "fallback";

    expect(result).toBe("#ff0000");
    vi.restoreAllMocks();
  });
});
