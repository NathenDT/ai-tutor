const farmAnimals = document.getElementById("farm-animals");
const farmStatus = document.getElementById("farm-status");

async function loadFarm() {
  if (!farmAnimals || !farmStatus) return;

  farmStatus.textContent = "Loading farm...";
  farmStatus.className = "store-status";

  try {
    const response = await fetch("/api/store");
    if (response.status === 401) {
      window.location.href = "/";
      return;
    }

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Could not load your farm.");
    }

    renderFarm(Array.isArray(data.items) ? data.items : []);
  } catch (error) {
    console.error("Could not load farm:", error);
    farmAnimals.replaceChildren();
    farmStatus.textContent = error.message || "Could not load your farm.";
    farmStatus.className = "store-status disconnected";
  }
}

function renderFarm(items) {
  const ownedAnimals = items.filter((item) => item.owned);

  if (!ownedAnimals.length) {
    farmStatus.textContent = "No animals yet. Unlock one in the store.";
    farmStatus.className = "store-status empty";
    farmAnimals.replaceChildren(renderEmptyFarm());
    return;
  }

  farmStatus.textContent = `${ownedAnimals.length} animal${ownedAnimals.length === 1 ? "" : "s"} on your farm.`;
  farmStatus.className = "store-status connected";
  farmAnimals.replaceChildren(...ownedAnimals.map(renderFarmAnimal));
}

function renderFarmAnimal(item) {
  const card = document.createElement("article");
  card.className = "farm-animal-card";

  const emoji = document.createElement("div");
  emoji.className = "animal-emoji";
  emoji.textContent = item.emoji;

  const title = document.createElement("h3");
  title.textContent = item.name;

  const badge = document.createElement("p");
  badge.className = "animal-price";
  badge.textContent = "Owned";

  card.append(emoji, title, badge);
  return card;
}

function renderEmptyFarm() {
  const empty = document.createElement("article");
  empty.className = "farm-empty";

  const title = document.createElement("h3");
  title.textContent = "Your farm is waiting.";

  const copy = document.createElement("p");
  copy.textContent = "Buy an animal emoji from the store and it will appear here.";

  const link = document.createElement("a");
  link.className = "btn";
  link.href = "/store";
  link.textContent = "Open Store";

  empty.append(title, copy, link);
  return empty;
}

loadFarm();
