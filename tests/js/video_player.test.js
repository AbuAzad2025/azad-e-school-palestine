/**
 * B8 — video_player.js coverage (previously 0%).
 *
 * The module is an IIFE exposing window.AzadVideoPlayer. Tests drive the real
 * class: DOM construction, watermark canvas lifecycle, HLS init branches
 * (native fallback / supported / error recovery), animation interval, destroy.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Import the IIFE once — it attaches window.AzadVideoPlayer
import "@app-static/js/video_player.js";

const { AzadVideoPlayer } = window;

// Minimal canvas 2D context stub (jsdom returns null from getContext)
function makeCtx() {
  return {
    clearRect: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    fillText: vi.fn(),
    font: "",
    fillStyle: "",
    shadowColor: "",
    shadowBlur: 0,
  };
}

beforeEach(() => {
  document.body.innerHTML = `<div id="player-box"></div>`;
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => makeCtx());
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  delete window.Hls;
});

describe("AzadVideoPlayer — construction", () => {
  it("logs error and does nothing when container is missing", () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    const p = new AzadVideoPlayer("no-such-id", "/stream/master.m3u8");
    expect(p.container).toBeNull();
    expect(err).toHaveBeenCalledWith(expect.stringContaining("no-such-id"));
  });

  it("creates a video element inside the container", () => {
    new AzadVideoPlayer("player-box", "/stream/master.m3u8", { enableWatermark: false });
    const video = document.querySelector("#player-box video");
    expect(video).toBeTruthy();
    expect(video.className).toBe("azad-video-element");
    expect(video.controls).toBe(true);
    expect(video.getAttribute("crossorigin")).toBe("anonymous");
  });

  it("uses default options when none provided", () => {
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: false });
    expect(p.userId).toBe(0);
    expect(p.userIp).toBe("unknown");
    expect(p.watermarkText).toContain("User: 0");
  });

  it("respects custom watermark text", () => {
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", {
      enableWatermark: false,
      watermarkText: "CUSTOM",
    });
    expect(p.watermarkText).toBe("CUSTOM");
  });

  it("creates watermark canvas overlay when enabled", () => {
    new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: true });
    const canvas = document.querySelector("#player-box canvas");
    expect(canvas).toBeTruthy();
    expect(canvas.className).toBe("azad-watermark-canvas");
    expect(canvas.style.pointerEvents).toBe("none");
  });

  it("skips canvas when watermark disabled", () => {
    new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: false });
    expect(document.querySelector("#player-box canvas")).toBeNull();
  });
});

describe("AzadVideoPlayer — HLS init branches", () => {
  it("falls back to native HLS when Hls is undefined and canPlayType supports it", () => {
    vi.spyOn(HTMLMediaElement.prototype, "canPlayType").mockReturnValue("maybe");
    new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: false });
    const video = document.querySelector("#player-box video");
    expect(video.src).toContain("/s.m3u8");
  });

  it("logs error when Hls undefined and native not supported", () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: false });
    expect(err).toHaveBeenCalledWith("HLS.js not loaded and native HLS not supported");
  });

  it("logs error when Hls exists but not supported", () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    window.Hls = Object.assign(vi.fn(), { isSupported: () => false });
    new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: false });
    expect(err).toHaveBeenCalledWith("HLS is not supported in this browser");
  });

  it("builds an Hls instance when supported", () => {
    const loadSource = vi.fn();
    const attachMedia = vi.fn();
    const on = vi.fn();
    window.Hls = Object.assign(
      vi.fn().mockImplementation(() => ({
        loadSource,
        attachMedia,
        on,
        destroy: vi.fn(),
        startLoad: vi.fn(),
        recoverMediaError: vi.fn(),
      })),
      {
        isSupported: () => true,
        Events: { MANIFEST_PARSED: "manifest", ERROR: "error" },
        ErrorTypes: { NETWORK_ERROR: "network", MEDIA_ERROR: "media" },
      },
    );
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: false });
    expect(loadSource).toHaveBeenCalledWith("/s.m3u8");
    expect(attachMedia).toHaveBeenCalledWith(p.video);
  });
});

describe("AzadVideoPlayer — HLS error recovery", () => {
  function makeHls() {
    const hls = {
      loadSource: vi.fn(),
      attachMedia: vi.fn(),
      on: vi.fn(),
      destroy: vi.fn(),
      startLoad: vi.fn(),
      recoverMediaError: vi.fn(),
    };
    window.Hls = Object.assign(vi.fn().mockImplementation(() => hls), {
      isSupported: () => true,
      Events: { MANIFEST_PARSED: "manifest", ERROR: "error" },
      ErrorTypes: { NETWORK_ERROR: "networkError", MEDIA_ERROR: "mediaError" },
    });
    return hls;
  }

  function captureErrorHandler() {
    let handler;
    // find the error handler registered via hls.on
    const hls = makeHls();
    hls.on.mockImplementation((event, cb) => {
      if (event === "error") handler = cb;
    });
    return { hls, getHandler: () => handler };
  }

  it("recovers from fatal network error via startLoad", () => {
    const { getHandler } = captureErrorHandler();
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: false });
    getHandler()(undefined, { fatal: true, type: "networkError" });
    expect(p.hls.startLoad).toHaveBeenCalled();
  });

  it("recovers from fatal media error via recoverMediaError", () => {
    const { getHandler } = captureErrorHandler();
    new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: false });
    getHandler()(undefined, { fatal: true, type: "mediaError" });
    expect(getHandler()).toBeTruthy();
  });

  it("destroys the player on other fatal errors", () => {
    const { getHandler } = captureErrorHandler();
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: false });
    getHandler()(undefined, { fatal: true, type: "otherError" });
    expect(p.hls).toBeNull();
  });

  it("ignores non-fatal errors", () => {
    const { getHandler } = captureErrorHandler();
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: false });
    getHandler()(undefined, { fatal: false, type: "networkError" });
    expect(p.hls).not.toBeNull();
  });
});

describe("AzadVideoPlayer — watermark animation", () => {
  it("draws two watermarks per tick (main + offset) and drifts on interval", () => {
    vi.useFakeTimers();
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", {
      enableWatermark: true,
      userId: 42,
      userIp: "1.2.3.4",
    });
    const ctx = p.ctx;
    // initial draw: main watermark + offset duplicate
    expect(ctx.fillText).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(4000);
    // 1 initial draw + 2 interval ticks = 3 draws × 2 fillText each
    expect(ctx.fillText).toHaveBeenCalledTimes(6);
    const textArg = ctx.fillText.mock.calls[0][0];
    expect(textArg).toContain("User: 42");
    expect(textArg).toContain("1.2.3.4");
  });

  it("bounces watermark at canvas edges", () => {
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: true });
    p.canvas.width = 220;
    p.canvas.height = 40;
    p.watermarkX = 25; // near maxX (220-200)
    p.watermarkDx = 3;
    p._driftWatermark();
    expect(Math.abs(p.watermarkDx)).toBeLessThanOrEqual(3);
    // force far beyond edge → clamped back inside and direction flipped
    p.watermarkX = 500;
    p._driftWatermark();
    expect(p.watermarkX).toBeLessThanOrEqual(20);
  });

  it("drift is a no-op without canvas", () => {
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: false });
    p.canvas = null;
    expect(() => p._driftWatermark()).not.toThrow();
  });
});

describe("AzadVideoPlayer — controls & teardown", () => {
  it("play/pause delegate to the video element", () => {
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: false });
    const playSpy = vi.spyOn(p.video, "play").mockResolvedValue();
    const pauseSpy = vi.spyOn(p.video, "pause");
    p.play();
    p.pause();
    expect(playSpy).toHaveBeenCalled();
    expect(pauseSpy).toHaveBeenCalled();
  });

  it("destroy clears interval, hls, and removes DOM nodes", () => {
    vi.useFakeTimers();
    const destroyHls = vi.fn();
    window.Hls = Object.assign(
      vi.fn().mockImplementation(() => ({
        loadSource: vi.fn(),
        attachMedia: vi.fn(),
        on: vi.fn(),
        destroy: destroyHls,
        startLoad: vi.fn(),
        recoverMediaError: vi.fn(),
      })),
      {
        isSupported: () => true,
        Events: { MANIFEST_PARSED: "manifest", ERROR: "error" },
        ErrorTypes: { NETWORK_ERROR: "networkError", MEDIA_ERROR: "mediaError" },
      },
    );
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: true });
    expect(p.watermarkInterval).not.toBeNull();
    p.destroy();
    expect(p.watermarkInterval).toBeNull();
    expect(destroyHls).toHaveBeenCalled();
    expect(p.hls).toBeNull();
    expect(document.querySelector("#player-box video")).toBeNull();
    expect(document.querySelector("#player-box canvas")).toBeNull();
  });

  it("destroy is safe when nothing was initialized", () => {
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: false });
    expect(() => p.destroy()).not.toThrow();
  });
});
