<script setup lang="ts">
import { computed, ref } from "vue";
import LogsView from "./LogsView.vue";
import { getApiClient, isHttpMode } from "../services/client";
import { productBoxStyle } from "../services/devOverlay";
import { useDevInspectSession } from "../services/useDevInspectSession";

const activeTab = ref("test");
const instanceId = ref("");
const persist = ref(true);
const step = ref(1);

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
  inspectFrame(getApiClient(), instanceId.value, file, { persist: persist.value });
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
    <h2>Developer Tools</h2>
    <el-alert
      v-if="!isHttpMode()"
      title="Web dev test tools require HTTP mode"
      description="Run the dashboard with VITE_API_MODE=http and start serve with --enable-web-test (ADR-014)."
      type="info"
      show-icon
      :closable="false"
    />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="Test" name="test">
        <div class="dev-tools__controls">
          <el-input v-model="instanceId" placeholder="Instance id (default: first instance)" />
          <el-checkbox v-model="persist">Persist evidence bundle</el-checkbox>
          <el-input-number v-model="step" :min="1" label="Video step" />
        </div>
        <div class="dev-tools__inputs">
          <label class="dev-tools__file">
            Take photo
            <input type="file" accept="image/*" capture="environment" @change="onFileSelected($event, 'image')" />
          </label>
          <label class="dev-tools__file">
            Upload image
            <input type="file" accept="image/*" @change="onFileSelected($event, 'image')" />
          </label>
          <label class="dev-tools__file">
            Upload video
            <input type="file" accept="video/*" @change="onFileSelected($event, 'video')" />
          </label>
        </div>

        <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
        <div v-if="busy" class="dev-tools__busy">Analyzing…</div>

        <div v-if="record" class="dev-tools__result">
          <div class="dev-tools__badge" :class="record.decision.business_result === 'OK' ? 'is-ok' : 'is-ng'">
            {{ record.decision.business_result }}
          </div>
          <p>
            Decision: {{ record.decision.internal_decision }} · Reasons:
            {{ record.decision.reason_codes.join(", ") || "none" }} · Missing:
            {{ record.decision.missing_components.join(", ") || "none" }}
          </p>
          <div v-if="imageUrl" class="dev-tools__preview">
            <img :src="imageUrl" alt="Uploaded test image" />
            <div v-if="overlayBox" class="dev-tools__box" :style="overlayStyle" />
          </div>
        </div>

        <div v-if="videoResult" class="dev-tools__result">
          <p>
            Analyzed {{ videoResult.analyzed_frames }} frames · OK {{ videoResult.ok_count }} ·
            NG {{ videoResult.ng_count }}
          </p>
          <el-table :data="videoResult.frames" max-height="360">
            <el-table-column prop="index" label="Frame" width="90" />
            <el-table-column prop="business_result" label="Result" width="110" />
            <el-table-column prop="internal_decision" label="Internal" width="120" />
            <el-table-column label="Reasons">
              <template #default="{ row }">{{ (row.reason_codes as string[]).join(", ") }}</template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
      <el-tab-pane label="Logs" name="logs">
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
