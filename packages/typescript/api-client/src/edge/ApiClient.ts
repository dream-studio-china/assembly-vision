import type {
  CameraState,
  CurrentInspection,
  DeviceStatus,
  EffectiveConfiguration,
  InspectionFilter,
  InspectionImages,
  InspectionRecord,
  InspectionRuntimeState,
  InspectionSummary,
  LogEvent,
  MediaMetadata,
  Page,
  StatisticsFilter,
  StatisticsSummary,
  TraceabilityView,
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
 *
 * Operator-workflow methods (current inspection, traceability, statistics,
 * images) target the future `/api/v1/inspection/current`,
 * `/api/v1/inspections/{id}/images`, `/api/v1/traceability/{sn}` and
 * `/api/v1/statistics` endpoints.
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

  // Operator workflow
  getCurrentInspection(): Promise<CurrentInspection>;
  confirmInspectionResult(): Promise<CurrentInspection>;
  continueNextInspection(): Promise<CurrentInspection>;
  triggerManualInspection(): Promise<CurrentInspection>;
  getInspectionImages(inspectionId: string): Promise<InspectionImages>;
  getTraceability(sn: string): Promise<TraceabilityView>;
  getStatistics(filter?: StatisticsFilter): Promise<StatisticsSummary>;
}
