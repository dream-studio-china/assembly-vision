// Renders a neutral SVG placeholder for the camera preview when no live media
// is available yet. The DetectionViewer aligns overlays to the source
// dimensions, so the placeholder matches the declared camera resolution.

export function placeholderFrame(width: number, height: number): string {
  const cols = 4;
  const rows = 3;
  const cellW = width / cols;
  const cellH = height / rows;
  const cells: string[] = [];
  for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < cols; c += 1) {
      const shade = 24 + ((r + c) % 2) * 14;
      cells.push(
        `<rect x="${c * cellW}" y="${r * cellH}" width="${cellW}" height="${cellH}" fill="rgb(${shade},${shade + 4},${shade + 8})"/>`,
      );
    }
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${cells.join("")}</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
