import { useEffect, useState } from "react";

// Node groups in fixed categorical order (the validated 8-slot palette from ninaivu, light and dark steps).
// Every node also gets a text label and the legend names each group, so color is never the only cue.
export const GROUPS = [
  { key: "Decision", light: "#2a78d6", dark: "#3987e5", note: "KEP" },
  { key: "PR", light: "#eb6834", dark: "#d95926", note: "pull request" },
  { key: "Person", light: "#1baf7a", dark: "#199e70", note: "contributor" },
  { key: "Issue", light: "#eda100", dark: "#c98500", note: "discussion" },
  { key: "Component", light: "#e87ba4", dark: "#d55181", note: "code area" },
  { key: "Team", light: "#6250d6", dark: "#9085e9", note: "SIG" },
  { key: "Technology", light: "#008300", dark: "#008300", note: "X → Y" },
] as const;

export const INK = {
  light: { primary: "#0b0b0b", secondary: "#52514e", link: "#c3c2b7", surface: "#fcfcfb" },
  dark: { primary: "#f0efec", secondary: "#c3c2b7", link: "#383835", surface: "#1a1a19" },
};

export function groupOf(label: string) {
  return GROUPS.find((g) => g.key === label) ?? GROUPS[0];
}

export function useDarkMode(): boolean {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return dark;
}
