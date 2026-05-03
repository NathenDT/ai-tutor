// --- Settings Page Logic ---

document.addEventListener('DOMContentLoaded', async () => {
  await loadSettings();
});

async function loadSettings() {
  try {
    const response = await fetch('/api/settings');
    if (!response.ok) {
      const message = await getErrorMessage(response, 'Failed to load settings.');
      console.error(message);
      if (response.status === 401) {
        window.location.href = '/';
      }
      return;
    }
    const data = await response.json();
    const settings = data.settings || {};

    document.getElementById('canvasUrl').value = settings.canvas_url || '';
    document.getElementById('canvasToken').value = settings.canvas_token || '';
  } catch (error) {
    console.error('Error loading settings:', error);
  }
}

document.getElementById('saveBtn').addEventListener('click', async () => {
  const canvasUrl = document.getElementById('canvasUrl').value.trim();
  const canvasToken = document.getElementById('canvasToken').value.trim();

  const settings = {
    canvas_url: canvasUrl || null,
    canvas_token: canvasToken || null,
  };

  try {
    const response = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    });

    if (response.ok) {
      alert('Settings saved successfully!');
    } else {
      const message = await getErrorMessage(response, 'Failed to save settings.');
      if (response.status === 401) {
        window.location.href = '/';
        return;
      }
      alert(message);
    }
  } catch (error) {
    console.error('Error saving settings:', error);
    alert('Error saving settings.');
  }
});

async function getErrorMessage(response, fallback) {
  try {
    const data = await response.json();
    return data.error || fallback;
  } catch (error) {
    return fallback;
  }
}
