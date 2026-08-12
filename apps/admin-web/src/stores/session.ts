/**
 * Pilot administrator session state (C3).
 *
 * The bearer credential is exchanged for the short-lived HttpOnly session
 * cookie once; the browser stores neither the credential nor a client-side
 * token. Guards use the authenticated identity from GET /auth/me.
 */
import { defineStore } from "pinia";

import { apiClient, type AdminMe } from "@assemblyvision/api-client-central";

interface SessionState {
  me: AdminMe | null;
  error: string | null;
}

export const useSessionStore = defineStore("session", {
  state: (): SessionState => ({ me: null, error: null }),

  getters: {
    isAuthenticated: (state) => state.me !== null,
  },

  actions: {
    async login(token: string): Promise<void> {
      this.error = null;
      try {
        await apiClient.login(token);
        this.me = await apiClient.getMe();
      } catch (error) {
        this.error = error instanceof Error ? error.message : "login failed";
        throw error;
      }
    },

    async restore(): Promise<boolean> {
      try {
        this.me = await apiClient.getMe();
        return true;
      } catch {
        this.me = null;
        return false;
      }
    },

    /**
     * Revoke the session cookie server-side, then drop the client state.
     * Local state is always cleared even if the network call fails, so the
     * UI never reports signed-in after the user asked to sign out.
     */
    async signOut(): Promise<void> {
      try {
        await apiClient.logout();
      } finally {
        this.me = null;
      }
    },

    clear(): void {
      this.me = null;
    },
  },
});
