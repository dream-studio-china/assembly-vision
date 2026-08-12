<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import {
  apiClient,
  type DesiredConfigurationPage,
} from "@assemblyvision/api-client-central";

const { t } = useI18n();
const page = ref<DesiredConfigurationPage | null>(null);
const error = ref<string | null>(null);

onMounted(async () => {
  try {
    page.value = await apiClient.listDesiredConfigurations();
  } catch (err) {
    error.value = err instanceof Error ? err.message : t("Failed to load desired configurations.");
  }
});
</script>

<template>
  <main class="assignments">
    <header>
      <h1>{{ t("Desired configurations") }}</h1>
      <p class="muted">
        {{ t("Current desired bundles per device. Assignment is desired state only.") }}
      </p>
    </header>

    <el-alert
      type="warning"
      show-icon
      :closable="false"
      class="notice"
      :title="t('Desired configuration only. Packages are installed manually in M1. Assignment is not proof of download, validation, or activation.')"
    />

    <el-alert v-if="error" :title="error" type="error" show-icon class="block" />

    <el-card class="block">
      <el-table
        v-if="page"
        :data="page.items"
        :empty-text="t('No desired configurations yet.')"
      >
        <el-table-column prop="device_id" :label="t('Assigned device')" width="260" show-overflow-tooltip />
        <el-table-column prop="revision" :label="t('Revision')" width="90" />
        <el-table-column prop="product_version_id" :label="t('Product version')" width="220" show-overflow-tooltip />
        <el-table-column prop="product_model_version_id" :label="t('Product model version')" width="220" show-overflow-tooltip />
        <el-table-column prop="component_model_version_id" :label="t('Component model version')" width="220" show-overflow-tooltip />
        <el-table-column prop="rule_version_id" :label="t('Rule version')" width="220" show-overflow-tooltip />
        <el-table-column prop="reason" :label="t('Reason')" min-width="140" show-overflow-tooltip />
        <el-table-column prop="assigned_by" :label="t('Assigned by')" width="120" />
        <el-table-column :label="t('Assigned at')" width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ new Date(row.assigned_at).toLocaleString() }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </main>
</template>

<style scoped>
.assignments {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1rem;
}

.notice {
  margin-top: 0.75rem;
}

.block {
  margin-top: 0.75rem;
}

.muted {
  color: var(--text-muted);
}
</style>
