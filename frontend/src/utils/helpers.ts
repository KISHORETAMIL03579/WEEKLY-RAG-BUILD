export function generateId(prefix = "id"): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * Single source of truth for temperature wording.
 * `preset` is the exact value the preset button applies; `max` is the upper bound of
 * the bucket used to label an arbitrary slider value.
 */
export interface TemperatureLevel {
  id: "deterministic" | "grounded" | "balanced" | "hallucination-risk";
  label: string;
  cls: "zero" | "low" | "mid" | "high";
  preset: number;
  max: number;
}

export const TEMPERATURE_LEVELS: readonly TemperatureLevel[] = [
  {
    id: "deterministic",
    label: "Deterministic",
    cls: "zero",
    preset: 0,
    max: 0,
  },
  { id: "grounded", label: "Grounded", cls: "low", preset: 0.2, max: 0.3 },
  { id: "balanced", label: "Balanced", cls: "mid", preset: 0.5, max: 0.7 },
  {
    id: "hallucination-risk",
    label: "Hallucination risk",
    cls: "high",
    preset: 0.8,
    max: Number.POSITIVE_INFINITY,
  },
];

/** Float-safe equality for slider values (0.1 + 0.2 style drift). */
export function sameNumber(a: number, b: number, epsilon = 0.001): boolean {
  return Math.abs(a - b) < epsilon;
}

export function getTempLevel(t: number): TemperatureLevel {
  if (sameNumber(t, 0)) return TEMPERATURE_LEVELS[0];
  return (
    TEMPERATURE_LEVELS.find((level) => t <= level.max + 0.0005) ||
    TEMPERATURE_LEVELS[TEMPERATURE_LEVELS.length - 1]
  );
}

export function getTempClass(t: number): TemperatureLevel["cls"] {
  return getTempLevel(t).cls;
}

export function getTempLabel(t: number): string {
  return getTempLevel(t).label;
}

export function escapeRegex(str: string): string {
  return (str || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** "1,234" / "—" for missing values. */
export function formatInt(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.round(value).toLocaleString()
    : "—";
}

export function formatMs(value: number | null | undefined, digits = 0): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  return `${value.toFixed(digits)} ms`;
}

export function formatUsd(
  value: number | null | undefined,
  digits = 6,
): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `$${value.toFixed(digits)}`
    : "—";
}

export function formatPct(
  value: number | null | undefined,
  digits = 1,
): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toFixed(digits)}%`
    : "—";
}

/** Ratio 0..1 -> "87.5%". */
export function formatRatioPct(
  value: number | null | undefined,
  digits = 1,
): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${(value * 100).toFixed(digits)}%`
    : "—";
}

export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? "null";
  } catch {
    return String(value);
  }
}

export function clipText(text: string, max = 220): string {
  const flat = (text || "").replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max).trimEnd()}…` : flat;
}

export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the legacy path
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}
