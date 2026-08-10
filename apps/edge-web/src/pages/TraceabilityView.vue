<script setup lang="ts">
// Product traceability: full inspection history for one SN, including
// reinspection attempts and the final status.

import { formatIsoTime } from "@assemblyvision/ui";
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { inspectionService } from "../services/inspectionService";
import type { TraceabilityView } from "@assemblyvision/api-client";

const route = useRoute();
const view = ref<TraceabilityView | null>(null);
const error = ref<string | null>(null);

onMounted(async () => {
  try {
    view.value = await inspectionService.getTraceability(String(route.params.sn));
  } catch (err) {
    error.value = String(err);
  }
});
</script>

<template>
  <div class="traceability">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <template v-if="view">
      <h2>Traceability · {{ view.sn }}</h2>

      <div class="traceability__final">
        <span class="label">Final status</span>
        <span class="final" :class="view.final_status === 'PASS' ? 'final--pass' : 'final--ng'">
          {{ view.final_status }}
        </span>
      </div>

      <el-table :data="view.attempts">
        <el-table-column prop="attempt" label="Inspection" width="120">
          <template #default="{ row }">Inspection #{{ row.attempt }}</template>
        </el-table-column>
        <el-table-column prop="timestamp" label="Time" min-width="170">
          <template #default="{ row }">{{ formatIsoTime(row.timestamp) }}</template>
        </el-table-column>
        <el-table-column label="Result" width="100">
          <template #default="{ row }">
            <span class="result" :class="row.result === 'PASS' ? 'result--pass' : 'result--ng'">
              {{ row.result }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="Reason" min-width="220">
          <template #default="{ row }">{{ row.reason || "-" }}</template>
        </el-table-column>
        <el-table-column prop="operator" label="Operator" width="140" />
        <el-table-column label="Images" width="110">
          <template #default="{ row }">
            <router-link :to="`/images/${row.inspection_id}`">view</router-link>
          </template>
        </el-table-column>
      </el-table>
    </template>
  </div>
</template>

<style scoped>
.traceability {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.traceability__final {
  display: flex;
  align-items: center;
  gap: 12px;
}
.label {
  color: var(--text-muted);
  font-size: 14px;
}
.final {
  font-size: 18px;
  font-weight: 700;
}
.final--pass {
  color: var(--status-ok);
}
.final--ng {
  color: var(--status-ng);
}
.result {
  border-radius: var(--radius-small);
  padding: 2px 12px;
  font-size: 12px;
}
.result--pass {
  background: var(--status-ok-soft);
  color: var(--status-ok);
}
.result--ng {
  background: var(--status-ng-soft);
  color: var(--status-ng);
}
</style>
