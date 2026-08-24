/**
 * Lightweight canvas-based charts for dashboards.
 *
 * Usage: <canvas data-chart="bar" data-chart-labels='[...]' data-chart-values='[...]' data-chart-colors='[...]'></canvas>
 */

const isRTL = () => document.dir === "rtl";

function getCanvasPixelRatio() {
  return window.devicePixelRatio || 1;
}

function setCanvasSize(canvas, rect) {
  const ratio = getCanvasPixelRatio(canvas.getContext("2d"));
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  canvas.getContext("2d").scale(ratio, ratio);
}

function getChartConfig(canvas) {
  try {
    return {
      type: canvas.dataset.chart || "bar",
      labels: JSON.parse(canvas.dataset.chartLabels || "[]"),
      values: JSON.parse(canvas.dataset.chartValues || "[]"),
      colors: JSON.parse(canvas.dataset.chartColors || "[]"),
      title: canvas.dataset.chartTitle || "",
    };
  } catch {
    return null;
  }
}

function getCssVar(name, fallback) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function drawBarChart(ctx, config, width, height) {
  const { labels, values, colors } = config;
  if (!values.length) return;

  const rtl = isRTL();
  const padding = { top: 30, right: 16, bottom: 40, left: 40 };
  const chartWidth = Math.max(1, width - padding.left - padding.right);
  const chartHeight = Math.max(1, height - padding.top - padding.bottom);
  const max = Math.max(...values, 1);
  const barCount = values.length;
  const gap = chartWidth / (barCount * 4);
  const barWidth = (chartWidth - gap * (barCount + 1)) / barCount;

  ctx.clearRect(0, 0, width, height);

  // Title
  if (config.title) {
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--text") || "#000";
    ctx.font = "600 14px Cairo, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(config.title, width / 2, 18);
  }

  // Axes
  ctx.strokeStyle =
    getComputedStyle(document.documentElement).getPropertyValue("--border") || "#ccc";
  ctx.beginPath();
  if (rtl) {
    ctx.moveTo(width - padding.right, padding.top);
    ctx.lineTo(width - padding.right, height - padding.bottom);
    ctx.lineTo(padding.left, height - padding.bottom);
  } else {
    ctx.moveTo(padding.left, padding.top);
    ctx.lineTo(padding.left, height - padding.bottom);
    ctx.lineTo(width - padding.right, height - padding.bottom);
  }
  ctx.stroke();

  values.forEach((value, i) => {
    const idx = rtl ? barCount - 1 - i : i;
    const x = padding.left + gap + idx * (barWidth + gap);
    const barHeight = (value / max) * chartHeight;
    const y = height - padding.bottom - barHeight;

    ctx.fillStyle = colors[i] || getCssVar("--azad-navy", "#014e7c");
    ctx.fillRect(x, y, barWidth, barHeight);

    // value label
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--text") || "#000";
    ctx.font = "600 11px Cairo, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(String(value), x + barWidth / 2, y - 5);

    // x label
    ctx.fillStyle =
      getComputedStyle(document.documentElement).getPropertyValue("--text-muted") || "#666";
    ctx.font = "11px Cairo, sans-serif";
    ctx.fillText(String(labels[i] || ""), x + barWidth / 2, height - padding.bottom + 16);
  });
}

function drawDoughnutChart(ctx, config, width, height) {
  const { labels, values, colors } = config;
  if (!values.length) return;

  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(centerX, centerY) - 24;
  const total = values.reduce((a, b) => a + b, 0) || 1;

  ctx.clearRect(0, 0, width, height);

  if (config.title) {
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--text") || "#000";
    ctx.font = "600 14px Cairo, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(config.title, centerX, 18);
  }

  let start = -Math.PI / 2;
  values.forEach((value, i) => {
    const slice = (value / total) * 2 * Math.PI;
    ctx.beginPath();
    ctx.moveTo(centerX, centerY);
    ctx.arc(centerX, centerY, radius, start, start + slice);
    ctx.closePath();
    ctx.fillStyle = colors[i] || getCssVar("--azad-navy", "#014e7c");
    ctx.fill();
    start += slice;
  });

  // Legend
  const rtl = isRTL();
  const legendX = rtl ? width - 16 : 16;
  let legendY = height - values.length * 18 - 8;
  ctx.textAlign = rtl ? "right" : "left";
  ctx.font = "12px Cairo, sans-serif";
  values.forEach((value, i) => {
    ctx.fillStyle = colors[i] || getCssVar("--azad-navy", "#014e7c");
    const boxX = rtl ? legendX - 10 : legendX;
    ctx.fillRect(boxX, legendY, 10, 10);
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--text") || "#000";
    const textX = rtl ? legendX - 16 : legendX + 16;
    ctx.fillText(`${labels[i] || ""}: ${value}`, textX, legendY + 9);
    legendY += 18;
  });
}

function renderChart(canvas) {
  const config = getChartConfig(canvas);
  if (!config) return;

  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  setCanvasSize(canvas, rect);
  const ctx = canvas.getContext("2d");
  const width = rect.width;
  const height = rect.height;

  if (config.type === "bar") {
    drawBarChart(ctx, config, width, height);
  } else if (config.type === "doughnut") {
    drawDoughnutChart(ctx, config, width, height);
  }
}

function initCharts() {
  document.querySelectorAll("canvas[data-chart]").forEach((canvas) => {
    renderChart(canvas);
  });
}

function debounce(fn, ms) {
  let t;
  return () => {
    clearTimeout(t);
    t = setTimeout(fn, ms);
  };
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initCharts);
} else {
  initCharts();
}

window.addEventListener("resize", debounce(initCharts, 200));

export { renderChart };
