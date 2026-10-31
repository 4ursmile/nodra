// Appearance: System / Light / Dark. <html data-theme="light|dark"> forces one; no attribute follows the system. theme-init.js sets it before first paint.
import { useState, useEffect } from "./vendor/preact-htm.js";

const KEY = "nodra_theme";
const mq = () => matchMedia("(prefers-color-scheme: dark)");
export const themePref = () => { const t = document.documentElement.getAttribute("data-theme"); return t === "light" || t === "dark" ? t : "system"; };
export const isDark = () => { const t = themePref(); return t === "dark" || (t === "system" && mq().matches); };
export function applyTheme(t) {
  const el = document.documentElement, forced = t === "light" || t === "dark";
  if (forced) el.setAttribute("data-theme", t); else el.removeAttribute("data-theme");
  try { if (forced) localStorage.setItem(KEY, t); else localStorage.removeItem(KEY); } catch (e) {}
  window.dispatchEvent(new Event("nodra-theme"));
}
// fn(dark) runs when the preference or the system setting changes; returns the stop function
export function onThemeChange(fn) {
  const f = () => fn(isDark()), m = mq();
  window.addEventListener("nodra-theme", f);
  if (m.addEventListener) m.addEventListener("change", f); else m.addListener(f);
  return () => { window.removeEventListener("nodra-theme", f); if (m.removeEventListener) m.removeEventListener("change", f); else m.removeListener(f); };
}
export function useDark() {
  const [d, set] = useState(isDark());
  useEffect(() => onThemeChange(set), []);
  return d;
}
