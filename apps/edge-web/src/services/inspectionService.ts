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
import { MockApiClient } from "@assemblyvision/api-client";
import { getApiClient } from "./client";

const operatorWorkflow = new MockApiClient();

export const inspectionService = {
  getCurrent(): Promise<CurrentInspection> {
    return operatorWorkflow.getCurrentInspection();
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
