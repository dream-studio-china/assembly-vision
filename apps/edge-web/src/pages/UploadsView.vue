<script setup lang="ts">
import type { UploadTask } from "@assemblyvision/api-client";
import { onMounted, ref } from "vue";
import { getApiClient } from "../services/client";

const tasks = ref<UploadTask[]>([]);
const loading = ref(false);

async function load(): Promise<void> {
  loading.value = true;
  try {
    const page = await getApiClient().listUploads(undefined, 50);
    tasks.value = page.items;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="uploads">
    <h2>Upload queue</h2>
    <el-table :data="tasks" v-loading="loading">
      <el-table-column prop="upload_task_id" label="Task ID" min-width="200" />
      <el-table-column prop="kind" label="Kind" width="110" />
      <el-table-column prop="status" label="Status" width="150" />
      <el-table-column prop="attempt_count" label="Attempts" width="90" />
      <el-table-column prop="next_attempt_at" label="Next attempt" min-width="170">
        <template #default="{ row }">{{ row.next_attempt_at ?? "-" }}</template>
      </el-table-column>
      <el-table-column prop="last_error_code" label="Last error" min-width="140">
        <template #default="{ row }">{{ row.last_error_code ?? "-" }}</template>
      </el-table-column>
    </el-table>
    <p class="uploads__hint">
      Manual retry is not available in the read-only M1 API (ADR-012); the
      scheduler will own retry in a later milestone.
    </p>
  </div>
</template>

<style scoped>
.uploads {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.uploads__hint {
  color: #6b7280;
  font-size: 13px;
}
</style>
