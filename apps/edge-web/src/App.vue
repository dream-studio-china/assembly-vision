<script setup lang="ts">
import { formatBytes } from "@assemblyvision/ui";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRuntimeStore } from "./stores/runtime";
import { isHttpMode } from "./services/client";

const runtime = useRuntimeStore();
const localTime = ref(new Date());
let clockTimer: ReturnType<typeof setInterval> | null = null;

const deviceCode = computed(() => runtime.status?.device_id.slice(0, 8).toUpperCase() ?? "LOCAL EDGE");
const diskWarning = computed(() => (runtime.status?.disk_free_bytes ?? Infinity) < 5 * 1024 ** 3);

onMounted(() => {
  void runtime.refresh();
  clockTimer = setInterval(() => {
    localTime.value = new Date();
  }, 1000);
});

onBeforeUnmount(() => {
  if (clockTimer !== null) clearInterval(clockTimer);
});
</script>

<template>
  <el-container class="app-shell">
    <el-header class="app-shell__header">
      <div class="app-shell__brand">
        <span>AssemblyVision</span>
        <small>EDGE / {{ deviceCode }}</small>
      </div>
      <nav class="app-shell__nav" aria-label="Primary navigation">
        <router-link to="/">Operator</router-link>
        <router-link to="/live">Live</router-link>
        <router-link to="/history">History</router-link>
        <router-link to="/statistics">Statistics</router-link>
        <router-link to="/uploads">Uploads</router-link>
        <router-link to="/health">Health</router-link>
        <router-link to="/configuration">Config</router-link>
        <router-link to="/logs">Logs</router-link>
        <router-link v-if="isHttpMode()" to="/login">Sign in</router-link>
      </nav>
      <div class="app-shell__telemetry" aria-label="Device telemetry">
        <span
          class="dot"
          :class="runtime.status?.inspection_ready ? 'dot--ok' : 'dot--ng'"
          aria-hidden="true"
        />
        <span>{{ runtime.status?.operational_state ?? "Loading" }}</span>
        <span class="app-shell__telemetry-item">
          Central: {{ runtime.status?.central_connected ? "connected" : "offline" }}
        </span>
        <span v-if="runtime.status" :class="{ 'app-shell__disk-warning': diskWarning }" class="app-shell__telemetry-item">
          Disk: {{ formatBytes(runtime.status.disk_free_bytes) }} free
        </span>
        <time class="app-shell__clock" :datetime="localTime.toISOString()">
          {{ localTime.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) }}
        </time>
      </div>
    </el-header>
    <el-main class="app-shell__main">
      <router-view />
    </el-main>
  </el-container>
</template>

<style>
html,
body,
#app {
  margin: 0;
  height: 100%;
}
</style>

<style scoped>
.app-shell {
  height: 100%;
}
.app-shell__header {
  display: flex;
  align-items: center;
  gap: 20px;
  min-height: 64px;
  height: auto;
  padding: 10px 20px;
  background: #12212b;
  color: #e8f0f3;
  border-bottom: 3px solid #176b87;
}
.app-shell__brand {
  display: flex;
  flex-direction: column;
  color: #fff;
  font-weight: 750;
  letter-spacing: 0.02em;
  white-space: nowrap;
}
.app-shell__brand small {
  margin-top: 2px;
  color: #98b0ba;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.app-shell__nav {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  min-width: 0;
  overflow-x: auto;
}
.app-shell__nav a {
  color: #c6d5da;
  text-decoration: none;
  font-size: 14px;
  white-space: nowrap;
  padding: 7px 9px;
  border-radius: 4px;
}
.app-shell__nav a.router-link-active {
  color: #fff;
  background: #245266;
  font-weight: 600;
}
.app-shell__telemetry {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  white-space: nowrap;
}
.app-shell__telemetry-item { color: #b9cbd1; }
.app-shell__clock {
  color: #fff;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}
.app-shell__disk-warning { color: #ffd17f; }
.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}
.dot--ok {
  background: #43a047;
}
.dot--ng {
  background: #e53935;
}
.app-shell__main {
  height: calc(100% - 64px);
  overflow: auto;
  padding: 20px;
}
@media (max-width: 1080px) {
  .app-shell__header { gap: 12px; }
  .app-shell__telemetry-item { display: none; }
}
@media (max-width: 720px) {
  .app-shell__header { align-items: flex-start; flex-wrap: wrap; padding: 10px 12px; }
  .app-shell__nav { order: 3; flex-basis: 100%; }
  .app-shell__main { padding: 12px; }
}
</style>
