// Operator-domain service facade.
//
// Pages and stores depend only on this module, never on the concrete client.
// Swapping the mock for the future FastAPI backend is a `getApiClient()`
// concern (VITE_API_BASE_URL), with no UI changes.
//
// The operator workflow actions (current inspection / confirm / next / manual)
// are a demonstration queue without a design 15.3 contract endpoint, so they
// always run against the deterministic mock client. Read-only views route
// through `getApiClient()` and therefore show real data when the edge backend
// is configured.

import type {
  ConfidenceDriftFilter,
  ConfidenceDriftReport,
  CurrentInspection,
  InspectionFilter,
  InspectionImages,
  InspectionRecord,
  InspectionSummary,
  LogEvent,
  Page,
  StatisticsFilter,
  StatisticsSummary,
  TraceabilityView,
} from "@assemblyvision/api-client";
import { MockApiClient } from "@assemblyvision/api-client";
import { getApiBaseUrl, getApiClient, isCrossOriginHttp, isHttpMode, loadMediaBlobUrl } from "./client";

const operatorWorkflow = new MockApiClient();

/**
 * Resolve image URLs to blob URLs for the cross-origin dev flow.
 *
 * A token-protected edge host cannot serve media to a cross-origin `<img>` tag
 * (the request carries no cookie or Authorization header), so the content is
 * fetched through the in-memory token and rendered from an object URL. Any
 * slot that fails to load keeps its original URL and the `<img>` error handler
 * marks it unavailable.
 */
async function resolveCrossOriginImages(images: InspectionImages): Promise<InspectionImages> {
  const resolve = async (url: string): Promise<string> => {
    if (!url) return url;
    try {
      return await loadMediaBlobUrl(url);
    } catch {
      return url;
    }
  };
  return {
    ...images,
    original: await resolve(images.original),
    detection: await resolve(images.detection),
    annotated: await resolve(images.annotated),
  };
}

/**
 * Content URL for one media item (design 16.5).
 *
 * Same-origin deployments render `<img>`/`<video>` directly against this URL so
 * the browser can send `Range` requests for clips. Cross-origin hosts cannot
 * serve media to a plain element (no credential header), so those deployments
 * fetch through `getMediaContentBlobUrl` instead.
 */
export function buildMediaUrl(mediaId: string): string {
  return `${getApiBaseUrl()}/api/v1/media/${encodeURIComponent(mediaId)}/content`;
}

export const inspectionService = {
  getCurrent(): Promise<CurrentInspection> {
    return operatorWorkflow.getCurrentInspection();
  },

  /** Fetch media content and return a renderable blob URL. */
  getMediaContentBlobUrl(mediaId: string): Promise<string> {
    return loadMediaBlobUrl(buildMediaUrl(mediaId));
  },

  confirmResult(): Promise<CurrentInspection> {
    return operatorWorkflow.confirmInspectionResult();
  },

  continueNext(): Promise<CurrentInspection> {
    return operatorWorkflow.continueNextInspection();
  },

  triggerManual(): Promise<CurrentInspection> {
    return operatorWorkflow.triggerManualInspection();
  },

  listHistory(filter?: InspectionFilter): Promise<Page<InspectionSummary>> {
    return getApiClient().listInspections(filter);
  },

  getInspection(inspectionId: string): Promise<InspectionRecord> {
    return getApiClient().getInspection(inspectionId);
  },

  async getImages(inspectionId: string): Promise<InspectionImages> {
    const images = await getApiClient().getInspectionImages(inspectionId);
    return isCrossOriginHttp() ? resolveCrossOriginImages(images) : images;
  },

  getTraceability(sn: string): Promise<TraceabilityView> {
    return getApiClient().getTraceability(sn);
  },

  getStatistics(filter?: StatisticsFilter): Promise<StatisticsSummary> {
    // The M1 edge API has no line identity yet, so the line filter only
    // exists in the mock. Dropping it in HTTP mode avoids a guaranteed 400
    // and a misleading UI control (AUDIT-001 4.5).
    if (isHttpMode() && filter && filter.line !== undefined) {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { line: _line, ...rest } = filter;
      return getApiClient().getStatistics(rest);
    }
    return getApiClient().getStatistics(filter);
  },

  getConfidenceDrift(filter: ConfidenceDriftFilter): Promise<ConfidenceDriftReport> {
    return getApiClient().getConfidenceDrift(filter);
  },

  listLogs(): Promise<Page<LogEvent>> {
    return getApiClient().listLogs(undefined, 50);
  },
};

export type { CurrentInspection, InspectionSummary, TraceabilityView };
