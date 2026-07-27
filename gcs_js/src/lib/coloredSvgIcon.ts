const coloredSvgCache = new Map<string, Promise<string>>();

function normalizeHexColor(hexColor: string): string {
  return /^#[0-9a-f]{6}$/i.test(hexColor) ? hexColor : "#FFFFFF";
}

/**
 * Fetch an SVG asset, replace its current-color paint with the requested color,
 * and return a data URL suitable for a Leaflet divIcon image.
 */
export function getColoredIcon(svgPath: string, hexColor: string): Promise<string> {
  const color = normalizeHexColor(hexColor);
  const cacheKey = `${svgPath}:${color}`;
  const cached = coloredSvgCache.get(cacheKey);
  if (cached) return cached;

  const request = fetch(svgPath)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Unable to load SVG icon: ${svgPath}`);
      }
      return response.text();
    })
    .then((source) => {
      const coloredSource = source
        .replace(/currentColor/gi, color)
        .replace(/#232629/gi, color)
        .replace(
          /<svg\b/,
          `<svg color="${color}" fill="${color}"`,
        );
      return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(coloredSource)}`;
    });

  coloredSvgCache.set(cacheKey, request);
  return request;
}
