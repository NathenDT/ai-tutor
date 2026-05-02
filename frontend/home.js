async function loadStreak() {
  const currentStreak = document.getElementById("current-streak");
  const longestStreak = document.getElementById("longest-streak");

  try {
    const response = await fetch("/api/streak");
    const streak = await response.json();

    if (!response.ok) {
      currentStreak.textContent = "0";
      longestStreak.textContent = "Log in to start";
      return;
    }

    currentStreak.textContent = streak.current_streak || 0;
    longestStreak.textContent = `Best: ${streak.longest_streak || 0}`;
  } catch (error) {
    currentStreak.textContent = "0";
    longestStreak.textContent = "Could not load";
    console.error("Could not load streak:", error);
  }
}

loadStreak();
