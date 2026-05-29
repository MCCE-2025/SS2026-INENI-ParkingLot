import { useTheme } from "../context/ThemeContext";
import type { ThemePreference } from "../lib/theme";

const OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "Auto" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export function ThemeToggle() {
  const { preference, setPreference } = useTheme();

  return (
    <label className="theme-toggle">
      <span className="theme-toggle__label">Theme</span>
      <select
        className="theme-toggle__select"
        value={preference}
        onChange={(e) => setPreference(e.target.value as ThemePreference)}
        aria-label="Color theme"
      >
        {OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}
