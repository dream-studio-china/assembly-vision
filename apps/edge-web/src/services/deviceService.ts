// Device-status service facade (camera, vision engine, inspection service,
// device state). Pages depend only on this module.

import type { CameraState, DeviceStatus } from "@assemblyvision/api-client";
import { getApiClient } from "./client";

export const deviceService = {
  getStatus(): Promise<DeviceStatus> {
    return getApiClient().getDeviceStatus();
  },

  getCamera(): Promise<CameraState> {
    return getApiClient().getCameraState();
  },
};
