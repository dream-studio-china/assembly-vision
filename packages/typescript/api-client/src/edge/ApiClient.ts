import type {
  CameraState,
  DeviceStatus,
  EffectiveConfiguration,
  InspectionFilter,
  InspectionRecord,
  InspectionRuntimeState,
  InspectionSummary,
  LogEvent,
  MediaMetadata,
  Page,
  UploadTask,
} from "./types";

/** Minimal acceptance envelope returned by mutating control endpoints. */
export type OperationResult = {
  accepted: boolean;
  operation_id: string;
  detail: string | null;
};

export type PauseResult = OperationResult & { state: InspectionRuntimeState | null };
export type ResumeResult = OperationResult & { state: InspectionRuntimeState | null };
export type RetryResult = OperationResult & { task: UploadTask | null };

/**
 * Edge REST client contract (docs/design/15-rest-api-and-events.md).
 *
 * The dashboard depends only on this interface. A mock implementation drives
 * development and tests without a backend; the HTTP implementation is used
 * against the future FastAPI service. UI code never imports either
 * implementation directly.
 */
export interface ApiClient {
  getHealthLive(): Promise<{ status: string }>;
  getHealthReady(): Promise<DeviceStatus>;
  getDeviceStatus(): Promise<DeviceStatus>;
  getCameraState(): Promise<CameraState>;
  getInspectionState(): Promise<InspectionRuntimeState>;
  pauseInspection(reason: string): Promise<PauseResult>;
  resumeInspection(reason: string): Promise<ResumeResult>;
  listInspections(filter?: InspectionFilter): Promise<Page<InspectionSummary>>;
  getInspection(inspectionId: string): Promise<InspectionRecord>;
  listInspectionMedia(inspectionId: string): Promise<MediaMetadata[]>;
  listUploads(cursor?: string, limit?: number): Promise<Page<UploadTask>>;
  retryUpload(uploadTaskId: string, reason: string): Promise<RetryResult>;
  getEffectiveConfiguration(): Promise<EffectiveConfiguration>;
  listLogs(cursor?: string, limit?: number): Promise<Page<LogEvent>>;
}
