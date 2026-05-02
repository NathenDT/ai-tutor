const loginForm = document.getElementById("login-form");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const loginError = document.getElementById("login-error");
const loginSubmit = document.getElementById("login-submit");

async function redirectIfAuthenticated() {
  try {
    const response = await fetch("/auth/me");
    const result = await response.json();
    if (result.authenticated) {
      window.location.href = "/home";
    }
  } catch (error) {
    console.error("Could not check auth state:", error);
  }
}

function showLoginError(message) {
  loginError.textContent = message;
  loginError.classList.remove("hidden");
}

function clearLoginError() {
  loginError.textContent = "";
  loginError.classList.add("hidden");
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearLoginError();
  loginSubmit.disabled = true;
  loginSubmit.textContent = "Logging in...";

  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        username: usernameInput.value,
        password: passwordInput.value,
      }),
    });

    const result = await response.json();
    if (!response.ok) {
      showLoginError(result.error || "Log in failed.");
      return;
    }

    window.location.href = "/home";
  } catch (error) {
    console.error("Login error:", error);
    showLoginError("Could not reach the server.");
  } finally {
    loginSubmit.disabled = false;
    loginSubmit.textContent = "Log In";
  }
});

redirectIfAuthenticated();
