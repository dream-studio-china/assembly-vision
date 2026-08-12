<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { apiClient, type RuleDetail } from "@assemblyvision/api-client-central";

const { t } = useI18n();
const route = useRoute();
const detail = ref<RuleDetail | null>(null);
const error = ref<string | null>(null);

onMounted(async () => {
  try {
    detail.value = await apiClient.getRule(Number(route.params.id));
  } catch (err) {
    error.value = err instanceof Error ? err.message : t("Failed to load the rule.");
  }
});
</script>

<template>
  <main class="detail">
    <header>
      <h1>{{ t("Rule {code}", { code: detail?.rule_code ?? route.params.id }) }}</h1>
      <router-link to="/rules" class="back">{{ t("Back to rules") }}</router-link>
    </header>

    <el-alert
      type="warning"
      show-icon
      :closable="false"
      class="notice"
      :title="t('Desired configuration only. Packages are installed manually in M1. Assignment is not proof of download, validation, or activation.')"
    />

    <el-alert v-if="error" :title="error" type="error" show-icon class="block" />

    <template v-if="detail">
      <el-card class="block">
        <template #header>{{ t("Rule") }}</template>
        <el-descriptions :column="3" border>
          <el-descriptions-item :label="t('Rule code')">{{ detail.rule_code }}</el-descriptions-item>
          <el-descriptions-item :label="t('Rule')">{{ detail.name }}</el-descriptions-item>
          <el-descriptions-item :label="t('Created (UTC)')">
            {{ new Date(detail.created_at).toLocaleString() }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <h2 class="section">{{ t("Governed versions") }}</h2>
      <el-empty v-if="detail.versions.length === 0" :description="t('No versions yet.')" />
      <el-card v-for="version in detail.versions" :key="version.version_id" class="block">
        <template #header>
          <span>{{ t("Version {n}", { n: version.version }) }}</span>
          <el-tag :type="version.status === 'PUBLISHED' ? 'success' : 'info'" size="small">
            {{ version.status === "PUBLISHED" ? t("Published") : t("Draft") }}
          </el-tag>
        </template>

        <el-descriptions :column="2" border>
          <el-descriptions-item :label="t('Version')">{{ version.version_id }}</el-descriptions-item>
          <el-descriptions-item :label="t('Rule version')">{{ version.product_version_id }}</el-descriptions-item>
          <el-descriptions-item :label="t('Barcode required')">
            {{ version.barcode_required ? t("Yes") : t("No") }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('Minimum usable frames')">
            {{ version.minimum_usable_frames }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('Uncertain maps to NG')">
            {{ version.uncertain_maps_to_ng ? t("Yes") : t("No") }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('Content hash')" class="mono">
            {{ version.content_sha256 }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('Published at')">
            {{ version.published_at ? new Date(version.published_at).toLocaleString() : "—" }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('Published by')">{{ version.published_by ?? "—" }}</el-descriptions-item>
          <el-descriptions-item :label="t('Publish reason')" :span="2">
            {{ version.publish_reason ?? "—" }}
          </el-descriptions-item>
        </el-descriptions>

        <h3 class="sub">{{ t("Mandatory gates") }}</h3>
        <el-empty
          v-if="Object.keys(version.mandatory_gates).length === 0"
          :description="t('No mandatory gates.')"
          :image-size="40"
        />
        <ul v-else class="gates">
          <li v-for="(expected, gate) in version.mandatory_gates" :key="gate" class="chip">
            {{ gate }}: {{ expected ? t("Yes") : t("No") }}
          </li>
        </ul>

        <h3 class="sub">{{ t("Component policies") }}</h3>
        <el-empty
          v-if="version.component_policies.length === 0"
          :description="t('No component policies.')"
          :image-size="40"
        />
        <el-table v-else :data="version.component_policies" size="small">
          <el-table-column prop="component_code" :label="t('Component')" width="160" />
          <el-table-column prop="high_confidence" :label="t('High confidence')" width="130" />
          <el-table-column prop="medium_confidence" :label="t('Medium confidence')" width="140" />
          <el-table-column prop="minimum_medium_detections" :label="t('Minimum medium detections')" width="200" />
          <el-table-column prop="expected_count" :label="t('Expected count')" width="130" />
          <el-table-column :label="t('Adjacent frames required')">
            <template #default="{ row }">{{ row.require_adjacent_frames ? t("Yes") : t("No") }}</template>
          </el-table-column>
        </el-table>

        <h3 class="sub">{{ t("Compatible component models") }}</h3>
        <el-empty
          v-if="version.compatible_model_version_ids.length === 0"
          :description="t('No compatible component models.')"
          :image-size="40"
        />
        <ul v-else class="chips">
          <li v-for="model_id in version.compatible_model_version_ids" :key="model_id" class="chip mono">
            {{ model_id }}
          </li>
        </ul>
      </el-card>
    </template>
  </main>
</template>

<style scoped>
.detail {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1rem;
}

.notice {
  margin-top: 0.75rem;
}

.block {
  margin-top: 0.75rem;
}

.section {
  margin-top: 1.25rem;
}

.sub {
  margin: 1rem 0 0.5rem;
}

.back {
  color: var(--text-muted);
}

.chips,
.gates {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding: 0;
  margin: 0;
}

.chip {
  padding: 0.2rem 0.6rem;
  border: 1px solid var(--border);
  background: var(--shell-strong);
  font-size: 12px;
}

.mono {
  font-family: var(--font-mono);
}
</style>
