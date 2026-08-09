<script setup lang="ts">
import type { UploadTask } from "@assemblyvision/api-client";
import { ElMessage } from "element-plus";
import { onMounted, ref } from "vue";
import { getApiClient } from "../services/client";

const tasks = ref<UploadTask[]>([]);
const loading = ref(false);
const retrying = ref<string | null>(null);

// Only RETRY_WAIT and PERMANENT_FAILURE tasks are eligible for the manual
// retry transition (E3c); succeeded/leased/cancelled tasks never are.
const RETRYABLE = new Set(["RETRY_WAIT", "PERMANENT_FAILURE"]);

async function load(): Promise<void> {
  loading.value = true;
  try {
    const page = await getApiClient().listUploads(undefined, 50);
    tasks.value = page.items;
  } finally {
    loading.value = false;
  }
}

async function retry(task: UploadTask): Promise<void> {
  retrying.value = task.upload_task_id;
  try {
    const updated = await getApiClient().retryUpload(task.upload_task_id);
    const index = tasks.value.findIndex((t) => t.upload_task_id === task.upload_task_id);
    if (index >= 0) tasks.value[index] = updated;
    ElMessage.success("Task reset to pending; it will drain on the next attempt");
  } catch (error) {
    // The server is authoritative: a concurrent worker claim or another
    // operator retry surfaces as a 409/404 problem without local mutation.
    const message = error instanceof Error ? error.message : String(error);
    ElMessage.error(`Retry failed: ${message}`);
    await load();
  } finally {
    retrying.value = null;
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
      <el-table-column label="Actions" width="110" fixed="right">
        <template #default="{ row }">
          <el-button
            size="small"
            type="primary"
            :disabled="!RETRYABLE.has(row.status)"
            :loading="retrying === row.upload_task_id"
            @click="retry(row)"
          >
            Retry
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <p class="uploads__hint">
      Manual retry is available only for <code>RETRY_WAIT</code> and
      <code>PERMANENT_FAILURE</code> tasks and preserves attempt history; a
      retried task never re-authorizes retention deletion before a new verified
      receipt (E3c).
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
