export function formatNumber(
  value: number | undefined,
  decimals: number,
  suffix = "",
): string {
  return Number.isFinite(value)
    ? `${value!.toFixed(decimals)}${suffix}`
    : "--";
}

export function formatCoordinate(value: number | undefined): string {
  return Number.isFinite(value) && value !== 0 ? value!.toFixed(7) : "--";
}

export function formatDistance(value: number | undefined): string {
  if (!Number.isFinite(value)) return "--";
  if (value! >= 1000) return `${(value! / 1000).toFixed(2)} km`;
  return `${value!.toFixed(0)} m`;
}

export function formatMetricValue(value: any, format: string, decimals?: number, suffix?: string): string {
  if (value === undefined || value === null) return "--";
  if (format === "number") {
    return formatNumber(value, decimals ?? 0, suffix);
  } else if (format === "coordinate") {
    return formatCoordinate(value);
  } else if (format === "distance") {
    return formatDistance(value);
  } else if (format === "degrees") {
    return `${Math.round(value)}\u00b0`;
  }
  return String(value);
}
