<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { apiClient, type ModelDetail } from "@assemblyvision/api-client-central";

const { t } = useI18n();
const route = useRoute();
const detail = ref<ModelDetail | null>(null);
const error = ref<string | null>(null);

onMounted(async () => {
  try {
    detail.value = await apiClient.getModel(Number(route.params.id));
  } catch (err) {
    error.value = err instanceof Error ? err.message : t("Failed to load the model.");
  }
});
</script>

<template>
  <main class="detail">
    <header>
      <h1>{{ t("Model {code}", { code: detail?.model_code ?? route.params.id }) }}</h1>
      <router-link to="/models" class="back">{{ t("Back to models") }}</router-link>
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
        <template #header>{{ t("Model") }}</template>
        <el-descriptions :column="3" border>
          <el-descriptions-item :label="t('Model code')">{{ detail.model_code }}</el-descriptions-item>
          <el-descriptions-item :label="t('Model')">{{ detail.name }}</el-descriptions-item>
          <el-descriptions-item :label="t('Task')">{{ detail.task }}</el-descriptions-item>
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
          <el-descriptions-item :label="t('Version')" class="mono">{{ version.version_id }}</el-descriptions-item>
          <el-descriptions-item :label="t('Semantic version')">{{ version.semantic_version }}</el-descriptions-item>
          <el-descriptions-item :label="t('Edge version label')">{{ version.edge_version_label }}</el-descriptions-item>
          <el-descriptions-item :label="t('Runtime')">{{ version.runtime }}</el-descriptions-item>
          <el-descriptions-item :label="t('Input size')">
            {{ version.input_width }} × {{ version.input_height }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('Manifest hash')" class="mono">
            {{ version.manifest_sha256 }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('Published at')">
            {{ version.published_at ? new Date(version.published_at).toLocaleString() : "—" }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('Published by')">{{ version.published_by ?? "—" }}</el-descriptions-item>
          <el-descriptions-item :label="t('Publish reason')" :span="2">
            {{ version.publish_reason ?? "—" }}
          </el-descriptions-item>
        </el-descriptions>

        <h3 class="sub">{{ t("Classes") }}</h3>
        <ul class="chips">
          <li v-for="class_name in version.class_names" :key="class_name" class="chip">{{ class_name }}</li>
        </ul>

        <h3 class="sub">{{ t("Artifacts") }}</h3>
        <el-empty
          v-if="version.artifacts.length === 0"
          :description="t('No artifacts declared.')"
          :image-size="40"
        />
        <el-table v-else :data="version.artifacts" size="small">
          <el-table-column prop="name" :label="t('Artifacts')" width="140" />
          <el-table-column prop="uri" :label="t('URI')" min-width="200" show-overflow-tooltip />
          <el-table-column prop="sha256" :label="t('Checksum')" min-width="260" show-overflow-tooltip class-name="mono" />
          <el-table-column prop="size_bytes" :label="t('Size (bytes)')" width="130" />
        </el-table>

        <h3 v-if="version.limitations.length > 0" class="sub">{{ t("Limitations") }}</h3>
        <ul v-if="version.limitations.length > 0" class="gates">
          <li v-for="limitation in version.limitations" :key="limitation" class="chip">
            {{ limitation }}
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
