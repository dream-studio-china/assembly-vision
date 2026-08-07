// Pure load-target resolution so the kiosk/desktop shell can be unit-tested
// without launching Electron. The dashboard bundle is served from the built
// edge-web output in production and from the Vite dev server in development.

export type LoadTarget = {
  dev: boolean;
  devUrl: string;
  distIndexPath: string;
};

export function resolveLoadTarget(target: LoadTarget): string {
  if (target.dev) return target.devUrl;
  return target.distIndexPath;
}
