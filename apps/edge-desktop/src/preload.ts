// Minimal context-bridge API exposed to the dashboard renderer. Keep this
// surface tiny and review it on any change; the dashboard should not need
// desktop capabilities beyond this in the MVP.

import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("assemblyVisionDesktop", {
  platform: process.platform,
  versions: {
    electron: process.versions.electron ?? null,
    chrome: process.versions.chrome ?? null,
    node: process.versions.node ?? null,
  },
});
