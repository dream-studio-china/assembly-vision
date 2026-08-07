// Operator-domain service facade.
//
// Pages and stores depend only on this module, never on the concrete client.
// Swapping the mock for the future FastAPI backend is a `getApiClient()`
// concern (VITE_API_BASE_URL), with no UI changes.

import type {
  CurrentInspection,
  InspectionFilter,
  InspectionImages,
  InspectionSummary,
  LogEvent,
  Page,
  StatisticsFilter,
  StatisticsSummary,
  TraceabilityView,
} from "@assemblyvision/api-client";
import { getApiClient } from "./client";

export const inspectionService = {
  getCurrent(): Promise<CurrentInspection> {
    return getApiClient().getCurrentInspection();
  },

  confirmResult(): Promise<CurrentInspection> {
    return getApiClient().confirmInspectionResult();
  },

  continueNext(): Promise<CurrentInspection> {
    return getApiClient().continueNextInspection();
  },

  triggerManual(): Promise<CurrentInspection> {
    return getApiClient().triggerManualInspection();
  },

  listHistory(filter?: InspectionFilter): Promise<Page<InspectionSummary>> {
    return getApiClient().listInspections(filter);
  },

  getImages(inspectionId: string): Promise<InspectionImages> {
    return getApiClient().getInspectionImages(inspectionId);
  },

  getTraceability(sn: string): Promise<TraceabilityView> {
    return getApiClient().getTraceability(sn);
  },

  getStatistics(filter?: StatisticsFilter): Promise<StatisticsSummary> {
    return getApiClient().getStatistics(filter);
  },

  listLogs(): Promise<Page<LogEvent>> {
    return getApiClient().listLogs(undefined, 50);
  },
};

export type { CurrentInspection, InspectionSummary, TraceabilityView };
