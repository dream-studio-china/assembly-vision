import type { DeviceStatus } from "@assemblyvision/api-client";
import { defineStore } from "pinia";
import { i18n } from "../i18n";

export type AlertSeverity = "critical" | "warning" | "info";

export type Alert = {
  id: string;
  severity: AlertSeverity;
  code: string;
  message: string;
  guidance: string;
  firstSeenAt: string;
  lastSeenAt: string;
  cleared: boolean;
  clearedAt: string | null;
};

const HISTORY_LIMIT = 20;

/**
 * Derive a compact human-readable byte count without importing the UI package
 * (which pulls SFCs and would break the node test environment).
 */
function formatFreeBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"] as const;
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value >= 100 || unit === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unit]}`;
}

type UploadCircuitAware = DeviceStatus & { upload_circuit_state?: string };

type AlertCandidate = Omit<Alert, "firstSeenAt" | "lastSeenAt" | "cleared" | "clearedAt">;

function activeModelVersions(status: DeviceStatus): string {
  return [status.current_product_model_version_id, status.current_component_model_version_id]
    .filter((id): id is string => Boolean(id))
    .join(", ");
}

/**
 * Persistent alert set derived from a device status snapshot (design 16.7).
 * Alerts keep stable codes, severity, first/last observed timestamps, and an
 * active/cleared state; toasts supplement but never replace this presentation.
 * History is bounded so the cleared set cannot grow unboundedly in browser
 * memory.
 */
export const useAlertsStore = defineStore("alerts", {
  state: () => ({
    alerts: [] as Alert[],
    history: [] as Alert[],
  }),

  actions: {
    setFromDeviceStatus(status: DeviceStatus): void {
      const now = new Date().toISOString();
      const candidates = deriveCandidates(status);
      const idToCandidate = new Map(candidates.map((c) => [c.id, c]));

      const existingById = new Map(this.alerts.filter((a) => !a.cleared).map((a) => [a.id, a]));
      this.alerts = candidates.map((c) => {
        const existing = existingById.get(c.id);
        return {
          ...c,
          firstSeenAt: existing ? existing.firstSeenAt : now,
          lastSeenAt: now,
          cleared: false,
          clearedAt: null,
        };
      });

      for (const active of existingById.values()) {
        if (idToCandidate.has(active.id)) continue;
        const cleared = { ...active, cleared: true, clearedAt: now, lastSeenAt: now };
        this.history = [cleared, ...this.history.filter((h) => h.id !== cleared.id)].slice(0, HISTORY_LIMIT);
      }
    },

    dismiss(id: string): void {
      const index = this.alerts.findIndex((a) => a.id === id);
      if (index === -1) return;
      const alert = this.alerts[index];
      if (alert.severity === "info") {
        this.alerts.splice(index, 1);
        return;
      }
      const cleared = { ...alert, cleared: true, clearedAt: new Date().toISOString() };
      this.alerts.splice(index, 1);
      this.history = [cleared, ...this.history.filter((h) => h.id !== id)].slice(0, HISTORY_LIMIT);
    },
  },
});

function deriveCandidates(status: DeviceStatus): AlertCandidate[] {
  const candidates: AlertCandidate[] = [];
  // The alert text follows the dashboard locale (i18n); codes stay stable so
  // tests and the API contract never depend on translated prose.
  const t = i18n.global.t;

  if (!status.inspection_ready) {
    candidates.push({
      id: "not_ready",
      severity: "critical",
      code: "NOT_READY",
      message: t("Inspection not ready"),
      guidance: t("Inspection cannot run until all readiness checks pass. Review camera, model, and rule status before resuming."),
    });
  }

  if (!status.camera_connected) {
    candidates.push({
      id: "camera_disconnected",
      severity: "critical",
      code: "CAMERA_DISCONNECTED",
      message: t("Camera disconnected"),
      guidance: t("Check cable and power; administrator may request reconnect."),
    });
  }

  if (!status.model_loaded) {
    const versions = activeModelVersions(status);
    candidates.push({
      id: "model_unavailable",
      severity: "critical",
      code: "MODEL_UNAVAILABLE",
      message: t("Model unavailable"),
      guidance: versions
        ? t("Active model versions: {versions}. Load the required models before inspecting.", { versions })
        : t("No active model version is present. Load the required models before inspecting."),
    });
  }

  if (!status.current_rule_version_id) {
    candidates.push({
      id: "rule_unavailable",
      severity: "critical",
      code: "RULE_UNAVAILABLE",
      message: t("Rule unavailable"),
      guidance: t("No active rule version is loaded. Inspection cannot run without a valid rule set."),
    });
  }

  if (status.storage_mode !== "NORMAL") {
    candidates.push({
      id: "disk_low",
      severity: status.storage_mode === "STOP" ? "critical" : "warning",
      code: "DISK_LOW",
      message: t("Disk space {mode}", { mode: status.storage_mode.toLowerCase() }),
      guidance: t("Free space: {bytes}. Manage retention so required evidence is never silently discarded.", {
        bytes: formatFreeBytes(status.storage_free_bytes),
      }),
    });
  }

  if (!status.central_connected) {
    candidates.push({
      id: "central_unreachable",
      severity: "warning",
      code: "CENTRAL_UNREACHABLE",
      message: t("Central server unreachable"),
      guidance: t("Inspection continues locally; uploads queue and retry automatically. Pending uploads: {count}.", {
        count: status.upload_pending_count,
      }),
    });
  }

  const circuitState = (status as UploadCircuitAware).upload_circuit_state;
  const uploadDegraded = status.upload_failure_rate > 0.5 || (circuitState !== undefined && circuitState !== "CLOSED");
  if (uploadDegraded) {
    candidates.push({
      id: "upload_degraded",
      severity: "warning",
      code: "UPLOAD_DEGRADED",
      message: t("Upload degraded"),
      guidance: t("Uploads are failing or the retry circuit is open. Review connectivity and the upload error details."),
    });
  }

  if (status.sync_ready === false) {
    candidates.push({
      id: "sync_pending",
      severity: "info",
      code: "SYNC_PENDING",
      message: t("Synchronization pending"),
      guidance: t("The device has not fully synchronized with the central server."),
    });
  }

  return candidates;
}
