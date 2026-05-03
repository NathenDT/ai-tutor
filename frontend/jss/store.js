const storeItems = document.getElementById("store-items");
const storeStatus = document.getElementById("store-status");
const storeBalance = document.getElementById("store-balance");
const navCoins = document.getElementById("current-coins");

let currentStore = { balance: 0, items: [] };

async function loadStore() {
  if (!storeItems || !storeStatus || !storeBalance) return;

  storeStatus.textContent = "Loading store...";
  storeStatus.className = "store-status";

  try {
    const response = await fetch("/api/store");
    if (response.status === 401) {
      window.location.href = "/";
      return;
    }

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Could not load store.");
    }

    currentStore = data;
    renderStore();
  } catch (error) {
    console.error("Could not load store:", error);
    storeStatus.textContent = error.message || "Could not load store.";
    storeStatus.className = "store-status disconnected";
  }
}

function renderStore() {
  storeBalance.textContent = currentStore.balance || 0;
  if (navCoins) navCoins.textContent = currentStore.balance || 0;

  const items = Array.isArray(currentStore.items) ? currentStore.items : [];
  storeItems.replaceChildren(...items.map(renderStoreItem));
  storeStatus.textContent = items.length ? "Choose an emoji to unlock." : "No items are available.";
  storeStatus.className = items.length ? "store-status connected" : "store-status empty";
}

function renderStoreItem(item) {
  const card = document.createElement("article");
  card.className = `animal-store-item${item.owned ? " owned" : ""}`;

  const emoji = document.createElement("div");
  emoji.className = "animal-emoji";
  emoji.textContent = item.emoji;

  const title = document.createElement("h3");
  title.textContent = item.name;

  const price = document.createElement("p");
  price.className = "animal-price";
  price.textContent = `${item.price} coins`;

  const button = document.createElement("button");
  button.className = item.owned ? "btn secondary" : "btn";
  button.type = "button";
  button.dataset.itemId = item.id;
  button.disabled = Boolean(item.owned) || !item.affordable;
  button.textContent = item.owned ? "Owned" : item.affordable ? "Buy" : "Need coins";

  card.append(emoji, title, price, button);
  return card;
}

storeItems?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-item-id]");
  if (!button || button.disabled) return;

  const itemId = button.dataset.itemId;
  button.disabled = true;
  button.textContent = "Buying...";

  try {
    const response = await fetch("/api/store/purchase", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId }),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "Could not buy item.");
    }

    currentStore.balance = result.balance;
    currentStore.items = currentStore.items.map((item) => {
      if (item.id !== result.item.id) {
        return { ...item, affordable: result.balance >= item.price };
      }
      return result.item;
    });
    renderStore();
    storeStatus.textContent = result.already_owned
      ? "You already own that emoji."
      : `Unlocked ${result.item.emoji} ${result.item.name}.`;
    storeStatus.className = "store-status connected";
  } catch (error) {
    console.error("Purchase failed:", error);
    renderStore();
    storeStatus.textContent = error.message || "Could not buy item.";
    storeStatus.className = "store-status disconnected";
  }
});

loadStore();
