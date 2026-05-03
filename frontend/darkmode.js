const toggle = document.getElementById("darkToggle");
const body = document.body;

function applyDarkMode(enabled) {
    body.classList.toggle("dark-mode", enabled);
    if (toggle) {
        toggle.checked = enabled;
    }
}

const darkModeEnabled = localStorage.getItem("darkMode") === "true";
applyDarkMode(darkModeEnabled);

if (toggle) {
    toggle.addEventListener("change", () => {
        const enabled = toggle.checked;
        localStorage.setItem("darkMode", enabled ? "true" : "false");
        applyDarkMode(enabled);
    });
}
