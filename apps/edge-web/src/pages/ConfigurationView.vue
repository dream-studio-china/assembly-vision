<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { getApiClient } from "../services/client";
import type { EffectiveConfiguration } from "@assemblyvision/api-client";

const { t } = useI18n();
const config = ref<EffectiveConfiguration | null>(null);
const error = ref<string | null>(null);

onMounted(async () => {
  try {
    config.value = await getApiClient().getEffectiveConfiguration();
  } catch (err) {
    error.value = String(err);
  }
});
</script>

<template>
  <div class="configuration">
    <h2>{{ t("Configuration") }}</h2>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-alert
      v-else
      type="info"
      :title="t('Read-only view. Local override editing and logs are administrator-only late-MVP features.')"
      :closable="false"
      show-icon
    />
    <template v-if="config">
      <p>{{ t("Revision: {revision}", { revision: config.revision }) }}</p>
      <p>{{ t("Checksum: {checksum}", { checksum: config.checksum_sha256 }) }}</p>
      <el-table :data="Object.entries(config.managed).map(([key, value]) => ({ key, value }))">
        <el-table-column prop="key" :label="t('Key')" />
        <el-table-column prop="value" :label="t('Value')">
          <template #default="{ row }">
            <code>{{ JSON.stringify(row.value) }}</code>
          </template>
        </el-table-column>
      </el-table>
    </template>
  </div>
</template>

<style scoped>
.configuration {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
</style>
