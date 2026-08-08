import { ref } from "vue";
import type { Ref } from "vue";
import type { ApiClient, InspectionRecord, VideoInspectResult } from "@assemblyvision/api-client";

export interface DevInspectSession {
  busy: Ref<boolean>;
  error: Ref<string | null>;
  record: Ref<InspectionRecord | null>;
  videoResult: Ref<VideoInspectResult | null>;
  imageUrl: Ref<string | null>;
  inspectFrame(client: ApiClient, instanceId: string, file: File, opts?: { persist?: boolean }): Promise<void>;
  inspectVideo(client: ApiClient, instanceId: string, file: File, opts?: { step?: number }): Promise<void>;
}

/**
 * Sequenced dev-inspect requests for the developer-tools page (ADR-014).
 *
 * A monotonically increasing request id invalidates any in-flight request the
 * moment a newer one starts. A stale response therefore can never publish its
 * record, surface an error, or clear `busy` while a newer request is still
 * running (PR-014 F10). `createPreviewUrl` is injectable so tests can avoid
 * `URL.createObjectURL`, which is absent outside browsers.
 */
export function useDevInspectSession(
  createPreviewUrl: (file: File) => string = (file) => URL.createObjectURL(file),
): DevInspectSession {
  const busy = ref(false);
  const error = ref<string | null>(null);
  const record = ref<InspectionRecord | null>(null);
  const videoResult = ref<VideoInspectResult | null>(null);
  const imageUrl = ref<string | null>(null);
  let latestRequestId = 0;

  function resetResult(): void {
    error.value = null;
    record.value = null;
    videoResult.value = null;
  }

  function inspectFrame(
    client: ApiClient,
    instanceId: string,
    file: File,
    opts?: { persist?: boolean },
  ): Promise<void> {
    const requestId = ++latestRequestId;
    resetResult();
    imageUrl.value = createPreviewUrl(file);
    busy.value = true;
    return client
      .devInspectFrame(instanceId, file, opts)
      .then((result) => {
        if (requestId !== latestRequestId) return;
        record.value = result;
      })
      .catch((err: unknown) => {
        if (requestId !== latestRequestId) return;
        error.value = err instanceof Error ? err.message : String(err);
      })
      .finally(() => {
        if (requestId !== latestRequestId) return;
        busy.value = false;
      });
  }

  function inspectVideo(
    client: ApiClient,
    instanceId: string,
    file: File,
    opts?: { step?: number },
  ): Promise<void> {
    const requestId = ++latestRequestId;
    resetResult();
    imageUrl.value = null;
    busy.value = true;
    return client
      .devInspectVideo(instanceId, file, opts)
      .then((result) => {
        if (requestId !== latestRequestId) return;
        videoResult.value = result;
      })
      .catch((err: unknown) => {
        if (requestId !== latestRequestId) return;
        error.value = err instanceof Error ? err.message : String(err);
      })
      .finally(() => {
        if (requestId !== latestRequestId) return;
        busy.value = false;
      });
  }

  return { busy, error, record, videoResult, imageUrl, inspectFrame, inspectVideo };
}
