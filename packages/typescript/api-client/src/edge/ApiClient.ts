import type {
  CameraState,
  ConfidenceDriftFilter,
  ConfidenceDriftReport,
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
  RetryUploadRequest,
  ReviewFilter,
  ReviewQueueItem,
  ReviewRecord,
  StatisticsFilter,
  StatisticsSummary,
  SubmitReviewRequest,
  TraceabilityView,
  UploadTask,
  VideoInspectResult,
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
  /**
   * Reset one eligible upload task to PENDING for a manual retry (E3c).
   *
   * Only `RETRY_WAIT` and `PERMANENT_FAILURE` tasks are eligible; the
   * transition is atomic server-side (PR-022 F03). Unknown tasks reject with
   * 404 `NOT_FOUND`; non-eligible tasks reject with 409 `TASK_NOT_RETRYABLE`.
   * The optional request carries the operator confirmation reason, which the
   * server records in its audit log (design 15.3.3).
   */
  retryUpload(uploadTaskId: string, request?: RetryUploadRequest): Promise<UploadTask>;
  getEffectiveConfiguration(): Promise<EffectiveConfiguration>;
  listLogs(cursor?: string, limit?: number): Promise<Page<LogEvent>>;

  /**
   * List the optional human-review queue with each inspection's review state
   * (design 24.4). Every inspection is listed; filter by business result and
   * `reviewed` to separate open from completed items.
   */
  listReviewQueue(filter?: ReviewFilter): Promise<Page<ReviewQueueItem>>;
  /** Return the append-only review history of one inspection (24.7). */
  listInspectionReviews(inspectionId: string): Promise<ReviewRecord[]>;
  /**
   * Append one human disposition for an inspection (24.3/24.6). Reviews are
   * optional and never rewrite the machine decision; the disposition must be
   * permitted for the machine outcome (422) and may only supersede a review
   * of the same inspection (409).
   */
  submitReview(inspectionId: string, request: SubmitReviewRequest): Promise<ReviewRecord>;

  // Operator workflow
  getCurrentInspection(): Promise<CurrentInspection>;
  confirmInspectionResult(): Promise<CurrentInspection>;
  continueNextInspection(): Promise<CurrentInspection>;
  triggerManualInspection(): Promise<CurrentInspection>;
  getInspectionImages(inspectionId: string): Promise<InspectionImages>;
  getTraceability(sn: string): Promise<TraceabilityView>;
  getStatistics(filter?: StatisticsFilter): Promise<StatisticsSummary>;
  getConfidenceDrift(filter?: ConfidenceDriftFilter): Promise<ConfidenceDriftReport>;

  // Gated web dev test harness (ADR-014); the server 404s unless started
  // with --enable-web-test.
  devInspectFrame(
    instanceId: string,
    image: Blob,
    opts?: { persist?: boolean; barcode?: string },
  ): Promise<InspectionRecord>;
  devInspectVideo(
    instanceId: string,
    video: Blob,
    opts?: { step?: number },
  ): Promise<VideoInspectResult>;
}
