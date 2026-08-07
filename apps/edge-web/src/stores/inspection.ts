import type { CurrentInspection } from "@assemblyvision/api-client";
import { defineStore } from "pinia";
import { inspectionService } from "../services/inspectionService";

/**
 * Holds the current operator inspection and drives the confirm / continue /
 * manual actions shared by the dashboard and live views.
 */
export const useInspectionStore = defineStore("inspection", {
  state: () => ({
    current: null as CurrentInspection | null,
    loading: false,
    error: null as string | null,
  }),

  actions: {
    async loadCurrent(): Promise<void> {
      this.loading = true;
      this.error = null;
      try {
        this.current = await inspectionService.getCurrent();
      } catch (error) {
        this.error = String(error);
      } finally {
        this.loading = false;
      }
    },

    async confirmResult(): Promise<void> {
      this.error = null;
      try {
        this.current = await inspectionService.confirmResult();
      } catch (error) {
        this.error = String(error);
      }
    },

    async continueNext(): Promise<void> {
      this.error = null;
      try {
        this.current = await inspectionService.continueNext();
      } catch (error) {
        this.error = String(error);
      }
    },

    async triggerManual(): Promise<void> {
      this.error = null;
      try {
        this.current = await inspectionService.triggerManual();
      } catch (error) {
        this.error = String(error);
      }
    },
  },
});
