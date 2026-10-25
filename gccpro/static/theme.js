/**
 * @file Theme switcher: cycles Auto (system) -> Clair -> Sombre and remembers the
 * choice in localStorage. Loaded without `defer` in <head> so the stored theme is
 * applied before first paint (no flash of the wrong theme).
 */
(function () {
  const KEY = "theme";
  const MODES = ["auto", "light", "dark"];
  const LABELS = { auto: "Auto", light: "Clair", dark: "Sombre" };

  /**
   * Read the stored mode; falls back to "auto" if storage is blocked or invalid.
   * @returns {string}
   */
  function load() {
    try {
      const value = localStorage.getItem(KEY);
      return MODES.includes(value) ? value : "auto";
    } catch (err) {
      return "auto";
    }
  }

  /**
   * Apply a mode to <html>: "auto" removes the attribute so the system theme wins.
   * @param {string} mode
   */
  function apply(mode) {
    if (mode === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", mode);
  }

  apply(load());

  /** Wire the header button once the DOM is ready. */
  document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("theme-toggle");
    if (!button) return;
    let mode = load();

    /** Refresh the visible label and the accessible name. */
    function render() {
      button.textContent = "Thème : " + LABELS[mode];
      button.setAttribute("aria-label", "Changer de thème (actuel : " + LABELS[mode] + ")");
    }

    button.addEventListener("click", () => {
      mode = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
      apply(mode);
      try {
        if (mode === "auto") localStorage.removeItem(KEY);
        else localStorage.setItem(KEY, mode);
      } catch (err) {
        /* Storage unavailable: the choice only lasts for this page view. */
      }
      render();
    });
    render();
  });
})();
