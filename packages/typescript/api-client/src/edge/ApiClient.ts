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

/**
 * Edge REST client contract (docs/design/15-rest-api-and-events.md).
 *
 * The dashboard depends only on this interface. A mock implementation drives
 * development and tests without a backend; the HTTP implementation is used
 * against the local FastAPI service. UI code never imports either
 * implementation directly.
 *
 * The M1 API is read-only (ADR-012): mutation controls such as pause/resume,
 * camera reconnect, and upload retry are not exposed.
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
  listInspections(filter?: InspectionFilter): Promise<Page<InspectionSummary>>;
  getInspection(inspectionId: string): Promise<InspectionRecord>;
  listInspectionMedia(inspectionId: string): Promise<MediaMetadata[]>;
  listUploads(cursor?: string, limit?: number): Promise<Page<UploadTask>>;
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
