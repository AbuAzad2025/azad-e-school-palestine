/**
 * Azad E-School — HLS Video Player with Dynamic Watermark
 *
 * Features:
 *   - HLS.js adaptive streaming
 *   - Dynamic HTML5 Canvas watermark (Student ID + IP + Timestamp)
 *   - Watermark drifts continuously across viewport
 *   - Anti-screen-recording protection
 *
 * P5-12: Dynamic watermark embeds user identity into video viewport.
 * P5-13: Watermark position updates every 2 seconds to prevent static capture.
 */

(() => {
  class AzadVideoPlayer {
    /**
     * @param {string} containerId - DOM element ID for the player container
     * @param {string} streamUrl - Master HLS playlist URL (signed)
     * @param {Object} options - Player configuration
     * @param {number} options.userId - Current user ID (for watermark)
     * @param {string} options.userIp - Client IP (for watermark)
     * @param {string} options.watermarkText - Custom watermark text
     * @param {boolean} options.enableWatermark - Enable/disable watermark (default: true)
     */
    constructor(containerId, streamUrl, options = {}) {
      this.container = document.getElementById(containerId);
      if (!this.container) {
        console.error(`Container #${containerId} not found`);
        return;
      }

      this.streamUrl = streamUrl;
      this.userId = options.userId || 0;
      this.userIp = options.userIp || "unknown";
      this.watermarkText =
        options.watermarkText || `User: ${this.userId} | ${this._getTimestamp()}`;
      this.enableWatermark = options.enableWatermark !== undefined ? options.enableWatermark : true;

      this.video = null;
      this.canvas = null;
      this.ctx = null;
      this.hls = null;
      this.watermarkInterval = null;
      this.watermarkX = 0;
      this.watermarkY = 0;
      this.watermarkDx = 1.5;
      this.watermarkDy = 1;

      this._init();
    }

    _init() {
      // Create video element
      this.video = document.createElement("video");
      this.video.className = "azad-video-element";
      this.video.controls = true;
      this.video.playsInline = true;
      this.video.setAttribute("crossorigin", "anonymous");
      this.container.appendChild(this.video);

      // Create watermark canvas overlay
      if (this.enableWatermark) {
        this._createWatermarkCanvas();
      }

      // Initialize HLS.js
      this._initHls();

      // Start watermark animation
      if (this.enableWatermark) {
        this._startWatermarkAnimation();
      }
    }

    _createWatermarkCanvas() {
      this.canvas = document.createElement("canvas");
      this.canvas.className = "azad-watermark-canvas";
      this.canvas.style.cssText =
        "position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:10;";

      // Position canvas over video
      this.container.style.position = "relative";
      this.container.appendChild(this.canvas);

      this.ctx = this.canvas.getContext("2d");

      // Resize canvas to match video
      this._resizeCanvas();
      window.addEventListener("resize", () => this._resizeCanvas());

      // Initial watermark position
      this.watermarkX = Math.random() * this.canvas.width * 0.6;
      this.watermarkY = Math.random() * this.canvas.height * 0.6;
    }

    _resizeCanvas() {
      if (this.canvas && this.video) {
        this.canvas.width = this.video.clientWidth || 640;
        this.canvas.height = this.video.clientHeight || 360;
      }
    }

    _initHls() {
      if (typeof Hls === "undefined") {
        // Fallback: native HLS support (Safari)
        if (this.video.canPlayType("application/vnd.apple.mpegurl")) {
          this.video.src = this.streamUrl;
        } else {
          console.error("HLS.js not loaded and native HLS not supported");
        }
        return;
      }

      if (!Hls.isSupported()) {
        console.error("HLS is not supported in this browser");
        return;
      }

      this.hls = new Hls({
        enableWorker: true,
        lowLatencyMode: false,
        maxBufferLength: 30,
        maxMaxBufferLength: 60,
        startFragPrefetch: true,
      });

      this.hls.loadSource(this.streamUrl);
      this.hls.attachMedia(this.video);

      this.hls.on(Hls.Events.MANIFEST_PARSED, () => {
        this._resizeCanvas();
      });

      this.hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              console.error("HLS network error, attempting recovery...");
              this.hls.startLoad();
              break;
            case Hls.ErrorTypes.MEDIA_ERROR:
              console.error("HLS media error, attempting recovery...");
              this.hls.recoverMediaError();
              break;
            default:
              console.error("HLS fatal error:", data);
              this.destroy();
              break;
          }
        }
      });
    }

    _startWatermarkAnimation() {
      // Update watermark position every 2 seconds
      this.watermarkInterval = setInterval(() => {
        this._drawWatermark();
        this._driftWatermark();
      }, 2000);

      // Initial draw
      this._drawWatermark();
    }

    _driftWatermark() {
      if (!this.canvas) return;

      // Random drift direction with bounded movement
      this.watermarkDx += (Math.random() - 0.5) * 2;
      this.watermarkDy += (Math.random() - 0.5) * 2;

      // Clamp velocity
      this.watermarkDx = Math.max(-3, Math.min(3, this.watermarkDx));
      this.watermarkDy = Math.max(-2, Math.min(2, this.watermarkDy));

      // Update position
      this.watermarkX += this.watermarkDx;
      this.watermarkY += this.watermarkDy;

      // Bounce off edges
      const maxX = this.canvas.width - 200;
      const maxY = this.canvas.height - 30;
      if (this.watermarkX < 0 || this.watermarkX > maxX) {
        this.watermarkDx *= -1;
        this.watermarkX = Math.max(0, Math.min(maxX, this.watermarkX));
      }
      if (this.watermarkY < 20 || this.watermarkY > maxY) {
        this.watermarkDy *= -1;
        this.watermarkY = Math.max(20, Math.min(maxY, this.watermarkY));
      }
    }

    _drawWatermark() {
      if (!this.ctx || !this.canvas) return;

      // Clear canvas
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

      // Build watermark text
      const timestamp = this._getTimestamp();
      const text = `User: ${this.userId} | ${this.userIp} | ${timestamp}`;

      // Draw watermark
      this.ctx.save();
      this.ctx.font = "14px monospace";
      this.ctx.fillStyle = "rgba(255, 255, 255, 0.3)";
      this.ctx.shadowColor = "rgba(0, 0, 0, 0.5)";
      this.ctx.shadowBlur = 2;
      this.ctx.fillText(text, this.watermarkX, this.watermarkY);
      this.ctx.restore();

      // Draw second watermark at offset (harder to crop)
      this.ctx.save();
      this.ctx.font = "12px monospace";
      this.ctx.fillStyle = "rgba(255, 255, 255, 0.15)";
      this.ctx.fillText(
        text,
        (this.watermarkX + this.canvas.width * 0.4) % this.canvas.width,
        (this.watermarkY + this.canvas.height * 0.5) % this.canvas.height,
      );
      this.ctx.restore();
    }

    _getTimestamp() {
      return new Date().toISOString().replace("T", " ").substring(0, 19);
    }

    play() {
      if (this.video) this.video.play();
    }

    pause() {
      if (this.video) this.video.pause();
    }

    destroy() {
      if (this.watermarkInterval) {
        clearInterval(this.watermarkInterval);
        this.watermarkInterval = null;
      }
      if (this.hls) {
        this.hls.destroy();
        this.hls = null;
      }
      if (this.container && this.video) {
        this.container.removeChild(this.video);
      }
      if (this.container && this.canvas) {
        this.container.removeChild(this.canvas);
      }
    }
  }

  // Export to global scope
  window.AzadVideoPlayer = AzadVideoPlayer;
})();
