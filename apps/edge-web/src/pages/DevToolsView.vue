<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import LogsView from "./LogsView.vue";
import { getApiClient, isHttpMode } from "../services/client";
import { productBoxStyle } from "../services/devOverlay";
import { useDevInspectSession } from "../services/useDevInspectSession";

const { t } = useI18n();
const activeTab = ref("test");
const instanceId = ref("");
const persist = ref(true);
const step = ref(1);
const simulatedBarcode = ref("");

const { busy, error, record, videoResult, imageUrl, inspectFrame, inspectVideo } =
  useDevInspectSession();

const overlayBox = computed(() => productBoxStyle(record.value));
const overlayStyle = computed(() => {
  const box = overlayBox.value;
  return box
    ? `left:${box.left};top:${box.top};width:${box.width};height:${box.height}`
    : "";
});

function handleImageFile(file: File): void {
  inspectFrame(getApiClient(), instanceId.value, file, {
    persist: persist.value,
    barcode: simulatedBarcode.value,
  });
}

function handleVideoFile(file: File): void {
  inspectVideo(getApiClient(), instanceId.value, file, { step: step.value });
}

function onFileSelected(event: Event, kind: "image" | "video"): void {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  if (kind === "image") handleImageFile(file);
  else handleVideoFile(file);
  input.value = "";
}
</script>

<template>
  <div class="dev-tools">
    <h2>{{ t("Developer Tools") }}</h2>
    <el-alert
      v-if="!isHttpMode()"
      :title="t('Web dev test tools require HTTP mode')"
      :description="t('Run the dashboard with VITE_API_MODE=http and start serve with --enable-web-test (ADR-014).')"
      type="info"
      show-icon
      :closable="false"
    />
    <el-tabs v-model="activeTab">
      <el-tab-pane :label="t('Test')" name="test">
        <div class="dev-tools__controls">
          <el-input v-model="instanceId" :placeholder="t('Instance id (default: first instance)')" />
          <el-input
            v-model="simulatedBarcode"
            :aria-label="t('Simulated barcode input')"
            :placeholder="t('Simulated barcode input (development only)')"
          />
          <el-checkbox v-model="persist">{{ t("Persist evidence bundle") }}</el-checkbox>
          <el-input-number v-model="step" :min="1" :label="t('Video step')" />
        </div>
        <div class="dev-tools__inputs">
          <label class="dev-tools__file">
            {{ t("Take photo") }}
            <input type="file" accept="image/*" capture="environment" @change="onFileSelected($event, 'image')" />
          </label>
          <label class="dev-tools__file">
            {{ t("Upload image") }}
            <input type="file" accept="image/*" @change="onFileSelected($event, 'image')" />
          </label>
          <label class="dev-tools__file">
            {{ t("Upload video") }}
            <input type="file" accept="video/*" @change="onFileSelected($event, 'video')" />
          </label>
        </div>

        <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
        <el-alert
          v-if="record?.decision.reason_codes.some((code) => code.startsWith('BARCODE_') || code.startsWith('PRODUCT_'))"
          :title="t('Identity verification failed: manual review required')"
          :description="record.decision.reason_codes.join(', ')"
          type="error"
          show-icon
          :closable="false"
        />
        <div v-if="busy" class="dev-tools__busy">{{ t("Analyzing…") }}</div>

        <div v-if="record" class="dev-tools__result">
          <div class="dev-tools__badge" :class="record.decision.business_result === 'OK' ? 'is-ok' : 'is-ng'">
            {{ record.decision.business_result }}
          </div>
          <p>
            {{
              t("Decision: {decision} · Reasons: {reasons} · Missing: {missing}", {
                decision: record.decision.internal_decision,
                reasons: record.decision.reason_codes.join(", ") || t("none"),
                missing: record.decision.missing_components.join(", ") || t("none"),
              })
            }}
          </p>
          <p>
            {{
              t("Barcode: {status} {value} · Product resolution: {resolution} {code}", {
                status: record.barcode_result.status,
                value: record.barcode_result.value ?? "—",
                resolution: record.product_resolution.status,
                code: record.product_resolution.product_code ?? "—",
              })
            }}
          </p>
          <div v-if="imageUrl" class="dev-tools__preview">
            <img :src="imageUrl" :alt="t('Uploaded test image')" />
            <div v-if="overlayBox" class="dev-tools__box" :style="overlayStyle" />
          </div>
        </div>

        <div v-if="videoResult" class="dev-tools__result">
          <p>
            {{
              t("Analyzed {count} frames · OK {ok} · NG {ng}", {
                count: videoResult.analyzed_frames,
                ok: videoResult.ok_count,
                ng: videoResult.ng_count,
              })
            }}
          </p>
          <el-table :data="videoResult.frames" max-height="360">
            <el-table-column prop="index" :label="t('Frame')" width="90" />
            <el-table-column prop="business_result" :label="t('Result')" width="110" />
            <el-table-column prop="internal_decision" :label="t('Internal')" width="120" />
            <el-table-column :label="t('Reasons')">
              <template #default="{ row }">{{ (row.reason_codes as string[]).join(", ") }}</template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
      <el-tab-pane :label="t('Logs')" name="logs">
        <LogsView />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.dev-tools {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.dev-tools__controls {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.dev-tools__inputs {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.dev-tools__file {
  display: inline-flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
}
.dev-tools__busy {
  color: var(--text-muted);
}
.dev-tools__result {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dev-tools__badge {
  align-self: flex-start;
  padding: 4px 12px;
  border-radius: var(--radius-small);
  font-weight: 700;
}
.dev-tools__badge.is-ok {
  background: var(--status-ok);
  color: var(--shell-text);
}
.dev-tools__badge.is-ng {
  background: var(--status-ng);
  color: var(--shell-text);
}
.dev-tools__preview {
  position: relative;
  display: inline-block;
  max-width: 640px;
}
.dev-tools__preview img {
  display: block;
  max-width: 100%;
}
.dev-tools__box {
  position: absolute;
  border: 2px solid var(--status-ok);
  box-sizing: border-box;
  pointer-events: none;
}
</style>
