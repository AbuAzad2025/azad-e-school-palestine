import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  resolve: {
    alias: {
      "@app-static": path.resolve(__dirname, "app/static"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["tests/js/setup.js"],
    include: ["tests/js/**/*.test.js"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov", "html"],
      reportsDirectory: "coverage/js",
      include: ["app/static/js/**/*.js"],
      exclude: ["app/static/js/ai-chat.js"],
    },
  },
});
