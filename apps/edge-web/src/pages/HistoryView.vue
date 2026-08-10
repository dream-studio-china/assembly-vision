<script setup lang="ts">
// Inspection history: server-side SN search, result filter, and cursor
// pagination (design 16.5).

import { StatusBadge, formatIsoTime, toDecisionStatus } from "@assemblyvision/ui";
import { onMounted, ref } from "vue";
import { inspectionService } from "../services/inspectionService";
import type { InspectionFilter, InspectionSummary } from "@assemblyvision/api-client";

const PAGE_SIZE = 25;

const items = ref<InspectionSummary[]>([]);
const loading = ref(false);
const loadingMore = ref(false);
const nextCursor = ref<string | null>(null);
const snFilter = ref("");
const resultFilter = ref<"" | "OK" | "NG">("");

let searchTimer: number | undefined;
let requestSeq = 0;

function buildFilter(cursor?: string): InspectionFilter {
  return {
    ...(snFilter.value.trim() ? { sn: snFilter.value.trim() } : {}),
    ...(resultFilter.value ? { business_result: resultFilter.value } : {}),
    cursor,
    limit: PAGE_SIZE,
  };
}

function scheduleSearch(): void {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => void load(), 300);
}

function onResultChange(): void {
  window.clearTimeout(searchTimer);
  void load();
}

async function load(): Promise<void> {
  const seq = ++requestSeq;
  nextCursor.value = null;
  loading.value = true;
  try {
    const page = await inspectionService.listHistory(buildFilter());
    if (seq !== requestSeq) return;
    items.value = page.items;
    nextCursor.value = page.next_cursor;
  } finally {
    if (seq === requestSeq) loading.value = false;
  }
}

async function loadMore(): Promise<void> {
  if (!nextCursor.value || loading.value || loadingMore.value) return;
  const seq = ++requestSeq;
  loadingMore.value = true;
  try {
    const page = await inspectionService.listHistory(buildFilter(nextCursor.value));
    if (seq !== requestSeq) return;
    items.value = [...items.value, ...page.items];
    nextCursor.value = page.next_cursor;
  } finally {
    if (seq === requestSeq) loadingMore.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="history">
    <h2>Inspection history</h2>

    <div class="history__filters">
      <el-input
        v-model="snFilter"
        placeholder="Search by SN"
        clearable
        aria-label="SN filter"
        @input="scheduleSearch"
        style="width: 220px"
      />
      <el-select
        v-model="resultFilter"
        placeholder="All results"
        clearable
        aria-label="Inspection result filter"
        @change="onResultChange"
        style="width: 160px"
      >
        <el-option label="PASS" value="OK" />
        <el-option label="NG" value="NG" />
      </el-select>
      <span class="history__count">{{ items.length }} rows</span>
    </div>

    <el-table :data="items" v-loading="loading" empty-text="No inspections found">
      <el-table-column prop="sn" label="SN" width="140">
        <template #default="{ row }">
          <router-link v-if="row.sn" :to="`/traceability/${row.sn}`">{{ row.sn }}</router-link>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column prop="completed_at" label="Timestamp" min-width="170">
        <template #default="{ row }">{{ formatIsoTime(row.completed_at) }}</template>
      </el-table-column>
      <el-table-column label="Result" width="110">
        <template #default="{ row }">
          <StatusBadge :status="toDecisionStatus(row.business_result, row.internal_decision)" />
        </template>
      </el-table-column>
      <el-table-column prop="reason_summary" label="Failure reason" min-width="200">
        <template #default="{ row }">
          <span v-if="row.reason_summary.length">{{ row.reason_summary.join(", ") }}</span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="Images" width="120">
        <template #default="{ row }">
          <router-link :to="`/images/${row.inspection_id}`">view</router-link>
        </template>
      </el-table-column>
    </el-table>

    <div class="history__more">
      <el-button v-if="nextCursor" :loading="loadingMore" @click="loadMore">Load more</el-button>
    </div>
  </div>
</template>

<style scoped>
.history {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.history__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}
.history__count {
  color: var(--text-muted);
  font-size: 13px;
}
.history__more {
  display: flex;
  justify-content: center;
}
</style>
