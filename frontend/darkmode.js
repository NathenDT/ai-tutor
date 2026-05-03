const toggle = document.getElementById("darkToggle");

// Load saved preference
if (localStorage.getItem("darkMode") === "true") {
    document.body.style.backgroundColor = "#1a1a1a";
    document.body.style.color = "#f0f0f0";
    toggle.checked = true;
}

// Toggle on click
toggle.addEventListener("change", () => {
    if (toggle.checked) {
        document.body.style.backgroundColor = "#1a1a1a";
        document.body.style.color = "#f0f0f0";
        localStorage.setItem("darkMode", "true");

        var container = document.querySelector(".container");
        if (container) {
            container.style.backgroundColor = "#1a1a1a";
        }
    } else {
        document.body.style.backgroundColor = "";
        document.body.style.color = "";
        localStorage.setItem("darkMode", "false");

        var container = document.querySelector(".container");
        if (container) {
            container.style.backgroundColor = "";
        }
    }
});