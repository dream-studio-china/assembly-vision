import { ApiError } from "@assemblyvision/api-client";
import { defineStore } from "pinia";
import { getApiClient, isMockMode } from "../services/client";

/**
 * Viewer/administrator session state for the HTTP edge API (design 16.3,
 * 16.10). Mock mode is always authenticated as a viewer + administrator; the
 * HTTP mode probes the backend once per page load to derive permissions.
 *
 * A failed probe is never treated as "authenticated": if the API is down the
 * router guard sends the user to /login rather than rendering broken pages.
 */
export const useSessionStore = defineStore("session", {
  state: () => ({
    authenticated: false,
    admin: false,
    checked: false,
    lastError: null as string | null,
  }),

  actions: {
    async check(): Promise<void> {
      if (isMockMode()) {
        this.authenticated = true;
        this.admin = true;
        this.checked = true;
        this.lastError = null;
        return;
      }
      this.checked = false;
      try {
        await getApiClient().getDeviceStatus();
        this.authenticated = true;
      } catch (error) {
        this.authenticated = false;
        this.admin = false;
        this.lastError =
          error instanceof ApiError && error.status === 401 ? null : errorMessage(error);
        this.checked = true;
        return;
      }
      try {
        await getApiClient().listLogs(undefined, 1);
        this.admin = true;
        this.lastError = null;
      } catch (error) {
        this.admin = false;
        this.lastError =
          error instanceof ApiError && error.status === 403 ? null : errorMessage(error);
      }
      this.checked = true;
    },

    reset(): void {
      this.authenticated = false;
      this.admin = false;
    },
  },
});

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
