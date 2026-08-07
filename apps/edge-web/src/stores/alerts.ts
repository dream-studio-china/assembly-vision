import { defineStore } from "pinia";

export type AlertSeverity = "critical" | "warning" | "info";

export type Alert = {
  id: string;
  severity: AlertSeverity;
  code: string;
  message: string;
  firstSeenAt: string;
};

/**
 * Active alert set derived from device status. Toasts supplement but never
 * replace the persistent status presentation (design 16.7).
 */
export const useAlertsStore = defineStore("alerts", {
  state: () => ({
    alerts: [] as Alert[],
  }),

  actions: {
    setFromStatus(inspectionReady: boolean, cameraConnected: boolean, centralConnected: boolean, diskFreeBytes: number): void {
      const next: Alert[] = [];
      if (!inspectionReady) {
        next.push({ id: "ready", severity: "critical", code: "NOT_READY", message: "Inspection not ready", firstSeenAt: new Date().toISOString() });
      }
      if (!cameraConnected) {
        next.push({ id: "camera", severity: "critical", code: "CAMERA_DISCONNECTED", message: "Camera disconnected", firstSeenAt: new Date().toISOString() });
      }
      if (!centralConnected) {
        next.push({ id: "central", severity: "warning", code: "CENTRAL_UNREACHABLE", message: "Central server unreachable", firstSeenAt: new Date().toISOString() });
      }
      if (diskFreeBytes < 5 * 1024 ** 3) {
        next.push({ id: "disk", severity: "warning", code: "DISK_LOW", message: "Low disk space", firstSeenAt: new Date().toISOString() });
      }
      this.alerts = next;
    },

    dismiss(id: string): void {
      this.alerts = this.alerts.filter((a) => a.id !== id);
    },
  },
});
