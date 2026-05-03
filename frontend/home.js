async function loadStreak() {
  const currentStreak = document.getElementById("current-streak");
  const longestStreak = document.getElementById("longest-streak");
  const currentCoins = document.getElementById("current-coins");

  try {
    const [streakResponse, coinsResponse] = await Promise.all([
      fetch("/api/streak"),
      fetch("/api/coins"),
    ]);
    const streak = await streakResponse.json();
    const coins = await coinsResponse.json();

    if (!streakResponse.ok) {
      currentStreak.textContent = "0";
      longestStreak.textContent = "Log in to start";
      if (currentCoins) currentCoins.textContent = "0";
      return;
    }

    currentStreak.textContent = streak.current_streak || 0;
    longestStreak.textContent = `Best: ${streak.longest_streak || 0}`;
    if (currentCoins) {
      currentCoins.textContent = coinsResponse.ok ? coins.balance || 0 : "0";
    }
  } catch (error) {
    currentStreak.textContent = "0";
    longestStreak.textContent = "Could not load";
    if (currentCoins) currentCoins.textContent = "0";
    console.error("Could not load streak:", error);
  }
}

loadStreak();
