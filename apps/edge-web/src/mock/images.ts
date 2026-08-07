// Local mock media resources for the operator prototype.
//
// These are pure frontend placeholders (camera preview background and demo
// frames). Real images arrive from the inspection API once the FastAPI layer
// is wired; the UI receives image URLs through `inspectionService` and never
// hard-codes business data here.

export function svgFrame(
  width: number,
  height: number,
  overlay = "",
  label = "ASSEMBLYVISION - CAMERA PREVIEW",
): string {
  const bg = Array.from({ length: 6 }, (_, i) => {
    const y = (i * 97) % height;
    const x = (i * 131) % width;
    return `<rect x="0" y="${y}" width="${width}" height="2" fill="#15171b"/><rect x="${x}" y="0" width="2" height="${height}" fill="#15171b"/>`;
  }).join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" fill="#0d0f12"/>${bg}${overlay}<text x="16" y="${height - 16}" fill="#5a6472" font-size="16">${label}</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/** Default camera preview shown while the line is waiting. */
export function mockCameraFrame(width = 800, height = 600): string {
  return svgFrame(width, height);
}
