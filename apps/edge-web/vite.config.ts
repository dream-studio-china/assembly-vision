import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";
import { assertProductionHttpMode } from "./src/vite-mode";

export default defineConfig({
  plugins: [
    vue(),
    {
      name: "enforce-http-mode-in-production",
      configResolved(config) {
        assertProductionHttpMode(config.env.VITE_API_MODE, config.command === "build");
      },
    },
  ],
  server: {
    port: 5173,
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          "vue-vendor": ["vue", "vue-router", "pinia"],
          "element-plus": ["element-plus"],
          echarts: ["echarts"],
        },
      },
    },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
});
