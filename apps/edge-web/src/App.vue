<script setup lang="ts">
import { onMounted } from "vue";
import { useRuntimeStore } from "./stores/runtime";

const runtime = useRuntimeStore();

onMounted(() => {
  void runtime.refresh();
});
</script>

<template>
  <el-container class="app-shell">
    <el-header class="app-shell__header">
      <div class="app-shell__brand">AssemblyVision Edge</div>
      <nav class="app-shell__nav">
        <router-link to="/">Live</router-link>
        <router-link to="/inspections">Inspections</router-link>
        <router-link to="/uploads">Uploads</router-link>
        <router-link to="/health">Health</router-link>
        <router-link to="/configuration">Configuration</router-link>
        <router-link to="/logs">Logs</router-link>
      </nav>
      <div class="app-shell__status">
        <span
          class="dot"
          :class="runtime.status?.inspection_ready ? 'dot--ok' : 'dot--ng'"
          aria-hidden="true"
        />
        {{ runtime.status?.operational_state ?? "…" }}
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
  gap: 24px;
  background: #1f2329;
  color: #e8eaf0;
}
.app-shell__brand {
  font-weight: 700;
  white-space: nowrap;
}
.app-shell__nav {
  display: flex;
  gap: 16px;
  flex: 1;
}
.app-shell__nav a {
  color: #c8cdd6;
  text-decoration: none;
  font-size: 14px;
}
.app-shell__nav a.router-link-active {
  color: #ffffff;
  font-weight: 600;
}
.app-shell__status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
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
  height: calc(100% - 60px);
  overflow: auto;
}
</style>
