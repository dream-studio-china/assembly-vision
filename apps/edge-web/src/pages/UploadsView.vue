<script setup lang="ts">
import type { UploadTask, UploadTaskState } from "@assemblyvision/api-client";
import { ElMessage, ElMessageBox } from "element-plus";
import { computed, onMounted, ref } from "vue";
import { getApiClient } from "../services/client";

const tasks = ref<UploadTask[]>([]);
const loading = ref(false);
const retrying = ref<string | null>(null);
const showAll = ref(false);

// Only RETRY_WAIT and PERMANENT_FAILURE tasks are eligible for the manual
// retry transition (E3c); succeeded/leased/cancelled tasks never are.
const RETRYABLE = new Set(["RETRY_WAIT", "PERMANENT_FAILURE"]);

// The queue page groups every task state but defaults to unfinished work
// (design 16.6); the toggle reveals succeeded/cancelled rows.
const UNFINISHED = new Set(["PENDING", "IN_PROGRESS", "RETRY_WAIT", "PERMANENT_FAILURE"]);

const COUNT_STATES: UploadTaskState[] = [
  "PENDING",
  "IN_PROGRESS",
  "RETRY_WAIT",
  "SUCCEEDED",
  "PERMANENT_FAILURE",
  "CANCELLED",
];

// Counts reflect the loaded page (single server page), not the whole queue.
const statusCounts = computed<Record<UploadTaskState, number>>(() => {
  const counts: Record<UploadTaskState, number> = {
    PENDING: 0,
    IN_PROGRESS: 0,
    RETRY_WAIT: 0,
    SUCCEEDED: 0,
    PERMANENT_FAILURE: 0,
    CANCELLED: 0,
  };
  for (const task of tasks.value) counts[task.status] += 1;
  return counts;
});

const visibleTasks = computed(() =>
  showAll.value ? tasks.value : tasks.value.filter((t) => UNFINISHED.has(t.status)),
);

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
  // Manual retry requires explicit confirmation and a reason (design 16.6);
  // the operator text is sent to the server, which records it in its audit log.
  let reason: string;
  try {
    const result = await ElMessageBox.prompt(
      `Reset upload task ${task.upload_task_id} to pending and retry it now?`,
      "Confirm manual retry",
      {
        confirmButtonText: "Retry",
        cancelButtonText: "Cancel",
        inputPlaceholder: "Reason for the retry (required)",
        inputValidator: (value) =>
          value.trim().length > 0 ? true : "A reason is required to confirm the retry",
      },
    );
    reason = result.value.trim();
  } catch {
    return; // The operator cancelled the confirmation.
  }
  retrying.value = task.upload_task_id;
  try {
    const updated = await getApiClient().retryUpload(task.upload_task_id, { reason });
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
    <div class="uploads__counts" aria-label="Upload queue state counts">
      <span v-for="state in COUNT_STATES" :key="state" class="uploads__count">
        <span class="uploads__count-value">{{ statusCounts[state] }}</span>
        {{ state }}
      </span>
    </div>
    <div class="uploads__toolbar">
      <el-switch v-model="showAll" active-text="All tasks" inactive-text="Unfinished only" />
    </div>
    <el-table :data="visibleTasks" v-loading="loading">
      <el-table-column prop="upload_task_id" label="Task ID" min-width="200" />
      <el-table-column prop="kind" label="Kind" width="110" />
      <el-table-column label="Inspection" min-width="200">
        <template #default="{ row }">
          <router-link v-if="row.inspection_id" :to="`/inspections/${row.inspection_id}`">
            {{ row.inspection_id }}
          </router-link>
          <span v-else>-</span>
        </template>
      </el-table-column>
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
.uploads__counts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.uploads__count {
  border: 1px solid var(--border);
  border-radius: var(--radius-small);
  padding: 2px 10px;
  font-size: 12px;
}
.uploads__count-value {
  font-weight: 600;
  margin-right: 4px;
}
.uploads__toolbar {
  display: flex;
  justify-content: flex-end;
}
.uploads__hint {
  color: var(--text-muted);
  font-size: 13px;
}
</style>
