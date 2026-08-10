import type { ApiError, CameraState, DeviceStatus, InspectionRuntimeState } from "@assemblyvision/api-client";
import { defineStore } from "pinia";
import { getApiClient } from "../services/client";

/**
 * Holds only the lightweight runtime snapshot and device status (design
 * 16.10). Historical inspection data is fetched page-locally, never mirrored
 * into the store.
 */
export const useRuntimeStore = defineStore("runtime", {
  state: () => ({
    status: null as DeviceStatus | null,
    runtime: null as InspectionRuntimeState | null,
    camera: null as CameraState | null,
    loading: false,
    error: null as string | null,
    // ISO timestamp of the last successful snapshot refresh; used to judge
    // whether the local API snapshot is fresh (design 16.11).
    lastUpdatedAt: null as string | null,
  }),

  actions: {
    async refresh(): Promise<void> {
      this.loading = true;
      this.error = null;
      const api = getApiClient();
      try {
        const [status, runtime, camera] = await Promise.all([
          api.getDeviceStatus(),
          api.getInspectionState(),
          api.getCameraState(),
        ]);
        this.status = status;
        this.runtime = runtime;
        this.camera = camera;
        this.lastUpdatedAt = new Date().toISOString();
      } catch (error) {
        this.error = (error as ApiError).message ?? String(error);
      } finally {
        this.loading = false;
      }
    },
  },
});
