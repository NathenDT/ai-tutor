const createUserForm = document.getElementById("create-user-form");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const confirmPasswordInput = document.getElementById("confirm-password");
const createUserError = document.getElementById("create-user-error");
const createUserSubmit = document.getElementById("create-user-submit");

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

function showCreateUserError(message) {
  createUserError.textContent = message;
  createUserError.classList.remove("hidden");
}

function clearCreateUserError() {
  createUserError.textContent = "";
  createUserError.classList.add("hidden");
}

createUserForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearCreateUserError();

  if (passwordInput.value !== confirmPasswordInput.value) {
    showCreateUserError("Passwords do not match.");
    return;
  }

  createUserSubmit.disabled = true;
  createUserSubmit.textContent = "Creating...";

  try {
    const response = await fetch("/auth/register", {
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
      showCreateUserError(result.error || "Could not create user.");
      return;
    }

    window.location.href = "/home";
  } catch (error) {
    console.error("Create user error:", error);
    showCreateUserError("Could not reach the server.");
  } finally {
    createUserSubmit.disabled = false;
    createUserSubmit.textContent = "Create User";
  }
});

redirectIfAuthenticated();
