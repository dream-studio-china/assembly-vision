<script setup lang="ts">
import type { BusinessResult, ReviewQueueItem } from "@assemblyvision/api-client";
import { ApiError } from "@assemblyvision/api-client";
import { formatIsoTime, reasonCodeLabel } from "@assemblyvision/ui";
import { ref } from "vue";
import { onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { getApiClient } from "../services/client";

// Optional human-in-the-loop review queue (docs/design/24-human-in-the-loop.md
// section 24.4). Every inspection is listed; the default view shows NG items
// first, and the reviewed filter separates open from completed items.

const { t } = useI18n();
const items = ref<ReviewQueueItem[]>([]);
const error = ref<string | null>(null);
const loading = ref(false);
const nextCursor = ref<string | null>(null);
const resultFilter = ref<"NG" | "OK" | "ALL">("NG");
const reviewedFilter = ref<"all" | "open" | "reviewed">("open");

const PAGE_SIZE = 25;
let requestGeneration = 0;

const DISPOSITION_LABELS: Record<string, string> = {
  CONFIRMED_NG: "Confirmed NG",
  CONFIRMED_OK: "Confirmed OK",
  CORRECTED_NG: "Corrected NG",
  INCONCLUSIVE: "Inconclusive",
  REINSPECT: "Reinspect",
};

async function load(reset: boolean): Promise<void> {
  const generation = ++requestGeneration;
  loading.value = true;
  error.value = null;
  try {
    const businessResult: BusinessResult | undefined =
      resultFilter.value === "ALL" ? undefined : resultFilter.value;
    const reviewed = reviewedFilter.value === "all" ? undefined : reviewedFilter.value === "reviewed";
    const page = await getApiClient().listReviewQueue({
      business_result: businessResult,
      reviewed,
      cursor: reset ? undefined : nextCursor.value ?? undefined,
      limit: PAGE_SIZE,
    });
    if (generation !== requestGeneration) return;
    items.value = reset ? page.items : [...items.value, ...page.items];
    nextCursor.value = page.next_cursor;
  } catch (err) {
    if (generation !== requestGeneration) return;
    error.value = err instanceof ApiError ? err.message : String(err);
  } finally {
    if (generation === requestGeneration) loading.value = false;
  }
}

function filterChanged(): void {
  void load(true);
}

function loadMore(): void {
  if (nextCursor.value) void load(false);
}

onMounted(() => {
  void load(true);
});
</script>

<template>
  <div class="reviews">
    <h2>{{ t("Review queue") }}</h2>
    <p class="reviews__intro">
      {{ t("Optional human review of machine decisions. Reviews are append-only and never rewrite the original decision.") }}
    </p>
    <div class="reviews__controls">
      <el-radio-group v-model="resultFilter" @change="filterChanged">
        <el-radio-button value="NG">NG</el-radio-button>
        <el-radio-button value="OK">OK</el-radio-button>
        <el-radio-button value="ALL">{{ t("All") }}</el-radio-button>
      </el-radio-group>
      <el-radio-group v-model="reviewedFilter" @change="filterChanged">
        <el-radio-button value="open">{{ t("Open") }}</el-radio-button>
        <el-radio-button value="reviewed">{{ t("Reviewed") }}</el-radio-button>
        <el-radio-button value="all">{{ t("All states") }}</el-radio-button>
      </el-radio-group>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <el-table :data="items" v-loading="loading" class="reviews__table">
      <el-table-column :label="t('Completed')" width="170">
        <template #default="{ row }">{{ formatIsoTime(row.completed_at) }}</template>
      </el-table-column>
      <el-table-column prop="business_result" :label="t('Result')" width="90">
        <template #default="{ row }">
          <span class="pill" :class="row.business_result === 'NG' ? 'pill--ng' : 'pill--ok'">
            {{ row.business_result }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="internal_decision" :label="t('Internal')" width="110" />
      <el-table-column prop="barcode" :label="t('Barcode')" width="140">
        <template #default="{ row }">{{ row.barcode ?? "-" }}</template>
      </el-table-column>
      <el-table-column :label="t('Reasons')">
        <template #default="{ row }">
          <span class="reviews__reasons">
            {{ (row.reason_summary as string[]).map((c) => t(reasonCodeLabel(c))).join(", ") || t("none") }}
          </span>
        </template>
      </el-table-column>
      <el-table-column :label="t('Review')" width="150">
        <template #default="{ row }">
          <span v-if="row.has_review" class="pill pill--present">
            {{ row.latest_disposition ? t(DISPOSITION_LABELS[row.latest_disposition]) : t("reviewed") }}
          </span>
          <span v-else class="pill pill--pending">{{ t("open") }}</span>
        </template>
      </el-table-column>
      <el-table-column label="" width="90">
        <template #default="{ row }">
          <router-link :to="`/inspections/${row.inspection_id}`">{{ t("Review") }}</router-link>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="nextCursor" class="reviews__more">
      <el-button :loading="loading" @click="loadMore">{{ t("Load more") }}</el-button>
    </div>
    <el-empty v-else-if="!loading && !items.length" :description="t('No inspections in this view')" />
  </div>
</template>

<style scoped>
.reviews {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.reviews h2 {
  margin: 0;
  font-size: 18px;
}
.reviews__intro {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}
.reviews__controls {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: center;
}
.reviews__table {
  width: 100%;
}
.reviews__reasons {
  font-size: 13px;
  color: var(--text-muted);
}
.reviews__more {
  display: flex;
  justify-content: center;
}
</style>
