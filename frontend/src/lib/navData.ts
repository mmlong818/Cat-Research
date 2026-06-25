// Safe cross-tool navigation with URL length protection.
// Short values (≤400 chars) go into the URL; long values use sessionStorage.
const SS_PREFIX = "navdata_";

export function encodeNavParam(key: string, value: string): string {
  if (value.length <= 400) return encodeURIComponent(value);
  sessionStorage.setItem(SS_PREFIX + key, value);
  return "__ss__";
}

export function decodeNavParam(key: string, raw: string | null): string {
  if (!raw) return "";
  if (raw === "__ss__") {
    const v = sessionStorage.getItem(SS_PREFIX + key) ?? "";
    sessionStorage.removeItem(SS_PREFIX + key);
    return v;
  }
  return raw; // URLSearchParams.get() already decodes
}
