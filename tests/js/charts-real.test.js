import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { renderChart } from "@app-static/js/components/charts.js";

// Mock getComputedStyle (jsdom returns empty strings)
const mockGetComputedStyle = vi.fn().mockReturnValue({
  getPropertyValue: vi.fn().mockImplementation((prop) => {
    const vars = {
      "--text": "#000",
      "--border": "#ccc",
      "--text-muted": "#666",
      "--azad-navy": "#014e7c",
    };
    return vars[prop] || "";
  }),
});
vi.stubGlobal("getComputedStyle", mockGetComputedStyle);

function createMockCtx() {
  return {
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
    _fillStyle: "",
    _strokeStyle: "",
    _font: "",
    _textAlign: "",
    get fillStyle() { return this._fillStyle; },
    set fillStyle(v) { this._fillStyle = v; },
    get strokeStyle() { return this._strokeStyle; },
    set strokeStyle(v) { this._strokeStyle = v; },
    get font() { return this._font; },
    set font(v) { this._font = v; },
    get textAlign() { return this._textAlign; },
    set textAlign(v) { this._textAlign = v; },
  };
}

function createCanvas(type, opts = {}) {
  const canvas = document.createElement("canvas");
  canvas.dataset.chart = type;
  if (opts.labels) canvas.dataset.chartLabels = JSON.stringify(opts.labels);
  if (opts.values) canvas.dataset.chartValues = JSON.stringify(opts.values);
  if (opts.colors) canvas.dataset.chartColors = JSON.stringify(opts.colors);
  if (opts.title !== undefined) canvas.dataset.chartTitle = opts.title;

  // Mock getBoundingClientRect
  canvas.getBoundingClientRect = vi.fn().mockReturnValue({
    width: 400,
    height: 300,
    top: 0,
    left: 0,
    right: 400,
    bottom: 300,
  });

  // Mock getContext
  const ctx = createMockCtx();
  canvas.getContext = vi.fn().mockReturnValue(ctx);

  return { canvas, ctx };
}

describe("Charts - renderChart (bar)", () => {
  it("renders bar chart with valid data", () => {
    const { canvas, ctx } = createCanvas("bar", {
      labels: ["A", "B", "C"],
      values: [10, 20, 30],
      colors: ["#f00", "#0f0", "#00f"],
      title: "Test Bar",
    });
    document.body.appendChild(canvas);

    renderChart(canvas);

    expect(ctx.clearRect).toHaveBeenCalled();
    expect(ctx.fillRect).toHaveBeenCalled();
    expect(ctx.fillText).toHaveBeenCalled();
  });

  it("renders bar chart without title", () => {
    const { canvas, ctx } = createCanvas("bar", {
      labels: ["X", "Y"],
      values: [5, 15],
    });
    document.body.appendChild(canvas);

    renderChart(canvas);

    expect(ctx.fillRect).toHaveBeenCalled();
  });

  it("renders bar chart with empty values", () => {
    const { canvas, ctx } = createCanvas("bar", {
      labels: [],
      values: [],
    });
    document.body.appendChild(canvas);

    renderChart(canvas);

    // Empty values → drawBarChart returns early
    expect(ctx.fillRect).not.toHaveBeenCalled();
  });

  it("uses fallback color when no colors provided", () => {
    const { canvas, ctx } = createCanvas("bar", {
      labels: ["A"],
      values: [10],
    });
    document.body.appendChild(canvas);

    renderChart(canvas);

    expect(ctx.fillRect).toHaveBeenCalled();
  });
});

describe("Charts - renderChart (doughnut)", () => {
  it("renders doughnut chart with valid data", () => {
    const { canvas, ctx } = createCanvas("doughnut", {
      labels: ["A", "B", "C"],
      values: [30, 50, 20],
      colors: ["#f00", "#0f0", "#00f"],
      title: "Test Doughnut",
    });
    document.body.appendChild(canvas);

    renderChart(canvas);

    expect(ctx.clearRect).toHaveBeenCalled();
    expect(ctx.arc).toHaveBeenCalled();
    expect(ctx.fill).toHaveBeenCalled();
  });

  it("renders doughnut chart without title", () => {
    const { canvas, ctx } = createCanvas("doughnut", {
      labels: ["X"],
      values: [100],
    });
    document.body.appendChild(canvas);

    renderChart(canvas);

    expect(ctx.arc).toHaveBeenCalled();
  });

  it("renders doughnut with empty values", () => {
    const { canvas, ctx } = createCanvas("doughnut", {
      labels: [],
      values: [],
    });
    document.body.appendChild(canvas);

    renderChart(canvas);

    expect(ctx.arc).not.toHaveBeenCalled();
  });

  it("renders legend with RTL support", () => {
    document.dir = "rtl";
    const { canvas, ctx } = createCanvas("doughnut", {
      labels: ["Ar", "Bn"],
      values: [60, 40],
      colors: ["#f00", "#0f0"],
    });
    document.body.appendChild(canvas);

    renderChart(canvas);

    // Legend text should be rendered
    const fillTextCalls = ctx.fillText.mock.calls.map((c) => c[0]);
    expect(fillTextCalls.some((t) => t.includes("Ar"))).toBe(true);
    document.dir = "ltr";
  });
});

describe("Charts - renderChart (invalid/missing config)", () => {
  it("returns early when no data-chart attribute", () => {
    const canvas = document.createElement("canvas");
    canvas.getBoundingClientRect = vi.fn().mockReturnValue({ width: 400, height: 300 });
    const ctx = createMockCtx();
    canvas.getContext = vi.fn().mockReturnValue(ctx);
    document.body.appendChild(canvas);

    renderChart(canvas);

    expect(ctx.clearRect).not.toHaveBeenCalled();
  });

  it("returns early when chart labels have invalid JSON", () => {
    const canvas = document.createElement("canvas");
    canvas.dataset.chart = "bar";
    canvas.dataset.chartLabels = "not-valid-json";
    canvas.dataset.chartValues = "[10,20]";
    canvas.getBoundingClientRect = vi.fn().mockReturnValue({ width: 400, height: 300 });
    const ctx = createMockCtx();
    canvas.getContext = vi.fn().mockReturnValue(ctx);
    document.body.appendChild(canvas);

    renderChart(canvas);

    // getChartConfig catches JSON parse error → returns null → early return
    expect(ctx.clearRect).not.toHaveBeenCalled();
  });

  it("returns early when canvas has zero dimensions", () => {
    const canvas = document.createElement("canvas");
    canvas.dataset.chart = "bar";
    canvas.dataset.chartLabels = '["A"]';
    canvas.dataset.chartValues = "[10]";
    canvas.getBoundingClientRect = vi.fn().mockReturnValue({ width: 0, height: 0 });
    const ctx = createMockCtx();
    canvas.getContext = vi.fn().mockReturnValue(ctx);
    document.body.appendChild(canvas);

    renderChart(canvas);

    // rect.width/height is 0 → early return
    expect(ctx.clearRect).not.toHaveBeenCalled();
  });

  it("ignores unknown chart types", () => {
    const { canvas, ctx } = createCanvas("pie", {
      labels: ["A"],
      values: [100],
    });
    document.body.appendChild(canvas);

    renderChart(canvas);

    expect(ctx.clearRect).not.toHaveBeenCalled();
  });
});

describe("Charts - RTL support in bar chart", () => {
  it("renders RTL bar chart", () => {
    document.dir = "rtl";
    const { canvas, ctx } = createCanvas("bar", {
      labels: ["A", "B"],
      values: [10, 20],
      colors: ["#f00", "#0f0"],
    });
    document.body.appendChild(canvas);

    renderChart(canvas);

    // RTL axes should be drawn from right side
    expect(ctx.moveTo).toHaveBeenCalled();
    expect(ctx.lineTo).toHaveBeenCalled();
    document.dir = "ltr";
  });
});

describe("Charts - Canvas default type", () => {
  it("defaults to bar when data-chart is empty", () => {
    const canvas = document.createElement("canvas");
    canvas.dataset.chartLabels = '["A"]';
    canvas.dataset.chartValues = "[10]";
    canvas.getBoundingClientRect = vi.fn().mockReturnValue({ width: 400, height: 300 });
    const ctx = createMockCtx();
    canvas.getContext = vi.fn().mockReturnValue(ctx);
    document.body.appendChild(canvas);

    renderChart(canvas);

    // Default type is "bar", so fillRect should be called
    expect(ctx.fillRect).toHaveBeenCalled();
  });
});
