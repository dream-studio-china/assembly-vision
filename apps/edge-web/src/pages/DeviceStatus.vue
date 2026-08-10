<script setup lang="ts">
// Device status monitoring: camera connection, vision engine, inspection
// service, and overall device state.

import { formatIsoTime } from "@assemblyvision/ui";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { deviceService } from "../services/deviceService";
import type { CameraState, DeviceStatus } from "@assemblyvision/api-client";

const { t } = useI18n();
const status = ref<DeviceStatus | null>(null);
const camera = ref<CameraState | null>(null);
const error = ref<string | null>(null);

type Row = { name: string; ok: boolean; detail: string };
const rows = ref<Row[]>([]);

function refresh(): void {
  rows.value = [
    {
      name: t("Camera connection"),
      ok: status.value?.camera_connected === true,
      detail: camera.value?.connected
        ? t("{width}×{height} {'@'} {fps} fps", {
            width: camera.value.source_width,
            height: camera.value.source_height,
            fps: camera.value.fps ?? "?",
          })
        : t("disconnected"),
    },
    {
      name: t("Vision engine"),
      ok: status.value?.model_loaded === true,
      detail: status.value?.model_loaded ? t("models loaded") : t("model missing"),
    },
    {
      name: t("Inspection service"),
      ok: status.value?.inspection_ready === true,
      detail: status.value?.inspection_ready ? t("ready") : t("not ready"),
    },
    {
      name: t("Device status"),
      ok: status.value?.operational_state === "READY" || status.value?.operational_state === "INSPECTING",
      detail: status.value?.operational_state ?? t("unknown"),
    },
  ];
}

onMounted(async () => {
  try {
    const [device, cam] = await Promise.all([deviceService.getStatus(), deviceService.getCamera()]);
    status.value = device;
    camera.value = cam;
    refresh();
  } catch (err) {
    error.value = String(err);
  }
});
</script>

<template>
  <div class="device">
    <h2>{{ t("Device status") }}</h2>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <el-table :data="rows">
      <el-table-column prop="name" :label="t('Component')" min-width="200" />
      <el-table-column :label="t('State')" width="130">
        <template #default="{ row }">
          <span class="pill" :class="row.ok ? 'pill--ok' : 'pill--ng'">
            {{ row.ok ? t("OK") : t("FAULT") }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="detail" :label="t('Detail')" min-width="220" />
    </el-table>

    <p class="device__meta">
      {{
        t("Observed at {time} · Storage {mode} · {free} GB free · Pending uploads {count}", {
          time: formatIsoTime(status?.observed_at),
          mode: status?.storage_mode ?? "NORMAL",
          free: ((status?.storage_free_bytes ?? 0) / 1024 ** 3).toFixed(1),
          count: status?.upload_pending_count ?? "-",
        })
      }}
    </p>
    <p v-if="status && status.alerts.length" class="device__alerts">
      {{ t("Server alerts: {alerts}", { alerts: status.alerts.join(", ") }) }}
    </p>
    <p v-if="status" class="device__meta">
      {{
        t("Integrity scan: checked {checked} · faults {faults} · checksummed {checksummed} · skipped {skipped}", {
          checked: status.integrity_scan_checked,
          faults: status.integrity_scan_faults,
          checksummed: status.integrity_scan_checksummed,
          skipped: status.integrity_scan_skipped,
        })
      }}
      {{
        t("(verify checksums: {state})", {
          state: status.integrity_verify_checksums ? t("on") : t("off"),
        })
      }}
    </p>
  </div>
</template>

<style scoped>
.device {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.device__meta {
  color: var(--text-muted);
  font-size: 13px;
}
.device__alerts {
  color: var(--status-warning);
  font-size: 13px;
  font-weight: 600;
}
.pill {
  display: inline-block;
  border-radius: var(--radius-small);
  padding: 2px 12px;
  font-size: 12px;
}
.pill--ok {
  background: var(--status-ok-soft);
  color: var(--status-ok);
}
.pill--ng {
  background: var(--status-ng-soft);
  color: var(--status-ng);
}
</style>
