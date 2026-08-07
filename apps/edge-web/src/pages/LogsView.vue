<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getApiClient } from "../services/client";
import type { LogEvent } from "@assemblyvision/api-client";

const logs = ref<LogEvent[]>([]);
const error = ref<string | null>(null);

onMounted(async () => {
  try {
    const page = await getApiClient().listLogs(undefined, 100);
    logs.value = page.items;
  } catch (err) {
    error.value = String(err);
  }
});
</script>

<template>
  <div class="logs">
    <h2>Logs</h2>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-table :data="logs">
      <el-table-column prop="logged_at" label="Time" width="200" />
      <el-table-column prop="level" label="Level" width="90" />
      <el-table-column prop="component" label="Component" width="180" />
      <el-table-column prop="message" label="Message" />
    </el-table>
  </div>
</template>

<style scoped>
.logs {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
</style>
