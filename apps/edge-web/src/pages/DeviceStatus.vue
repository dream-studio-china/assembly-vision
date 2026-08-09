<script setup lang="ts">
// Device status monitoring: camera connection, vision engine, inspection
// service, and overall device state.

import { formatIsoTime } from "@assemblyvision/ui";
import { onMounted, ref } from "vue";
import { deviceService } from "../services/deviceService";
import type { CameraState, DeviceStatus } from "@assemblyvision/api-client";

const status = ref<DeviceStatus | null>(null);
const camera = ref<CameraState | null>(null);
const error = ref<string | null>(null);

type Row = { name: string; ok: boolean; detail: string };
const rows = ref<Row[]>([]);

function refresh(): void {
  rows.value = [
    {
      name: "Camera connection",
      ok: status.value?.camera_connected === true,
      detail: camera.value?.connected ? `${camera.value.source_width}×${camera.value.source_height} @ ${camera.value.fps ?? "?"} fps` : "disconnected",
    },
    {
      name: "Vision engine",
      ok: status.value?.model_loaded === true,
      detail: status.value?.model_loaded ? "models loaded" : "model missing",
    },
    {
      name: "Inspection service",
      ok: status.value?.inspection_ready === true,
      detail: status.value?.inspection_ready ? "ready" : "not ready",
    },
    {
      name: "Device status",
      ok: status.value?.operational_state === "READY" || status.value?.operational_state === "INSPECTING",
      detail: status.value?.operational_state ?? "unknown",
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
    <h2>Device status</h2>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <el-table :data="rows">
      <el-table-column prop="name" label="Component" min-width="200" />
      <el-table-column label="State" width="130">
        <template #default="{ row }">
          <span class="pill" :class="row.ok ? 'pill--ok' : 'pill--ng'">
            {{ row.ok ? "OK" : "FAULT" }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="detail" label="Detail" min-width="220" />
    </el-table>

    <p class="device__meta">
      Observed at {{ formatIsoTime(status?.observed_at) }} · Storage
      {{ status?.storage_mode ?? "NORMAL" }} ·
      {{ ((status?.storage_free_bytes ?? 0) / 1024 ** 3).toFixed(1) }} GB free ·
      Pending uploads {{ status?.upload_pending_count ?? "-" }}
    </p>
    <p v-if="status && status.alerts.length" class="device__alerts">
      Server alerts: {{ status.alerts.join(", ") }}
    </p>
    <p v-if="status" class="device__meta">
      Integrity scan: checked {{ status.integrity_scan_checked }} ·
      faults {{ status.integrity_scan_faults }} ·
      checksummed {{ status.integrity_scan_checksummed }} ·
      skipped {{ status.integrity_scan_skipped }}
      (verify checksums: {{ status.integrity_verify_checksums ? "on" : "off" }})
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
  color: #6b7280;
  font-size: 13px;
}
.device__alerts {
  color: #b45309;
  font-size: 13px;
  font-weight: 600;
}
.pill {
  display: inline-block;
  border-radius: 999px;
  padding: 2px 12px;
  font-size: 12px;
}
.pill--ok {
  background: #e8f5e9;
  color: #1b5e20;
}
.pill--ng {
  background: #fdecea;
  color: #b71c1c;
}
</style>
