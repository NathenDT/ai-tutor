(function () {
  const STORAGE_KEY = "dark-mode";
  const root = document.documentElement;

  function readStoredPreference() {
    try {
      return localStorage.getItem(STORAGE_KEY) === "true";
    } catch (error) {
      return root.dataset.theme === "dark";
    }
  }

  function writeStoredPreference(enabled) {
    try {
      localStorage.setItem(STORAGE_KEY, enabled ? "true" : "false");
    } catch (error) {
      // Theme still applies for this page even when storage is unavailable.
    }
  }

  function setTheme(enabled, shouldPersist) {
    root.dataset.theme = enabled ? "dark" : "light";
    document.body.classList.toggle("dark-mode", enabled);

    for (const control of document.querySelectorAll("[data-theme-toggle], #darkToggle")) {
      if (control instanceof HTMLInputElement && control.type === "checkbox") {
        control.checked = enabled;
      } else {
        control.setAttribute("aria-pressed", String(enabled));
        const label = control.querySelector("[data-theme-label]");
        if (label) {
          label.textContent = enabled ? "Light" : "Dark";
        }
        const icon = control.querySelector("[data-theme-icon]");
        if (icon) {
          icon.textContent = enabled ? "L" : "D";
        }
      }
    }

    if (shouldPersist) {
      writeStoredPreference(enabled);
    }
  }

  function toggleTheme(event) {
    const control = event.currentTarget;
    const enabled =
      control instanceof HTMLInputElement && control.type === "checkbox"
        ? control.checked
        : root.dataset.theme !== "dark";
    setTheme(enabled, true);
  }

  function initialize() {
    setTheme(readStoredPreference(), false);

    for (const control of document.querySelectorAll("[data-theme-toggle], #darkToggle")) {
      if (control instanceof HTMLInputElement && control.type === "checkbox") {
        control.addEventListener("change", toggleTheme);
      } else {
        control.addEventListener("click", toggleTheme);
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
})();
