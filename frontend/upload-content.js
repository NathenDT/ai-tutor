const uploadForm = document.getElementById("pdf-upload-form");
const fileInput = document.getElementById("pdf-file");
const submitButton = document.getElementById("upload-submit");
const uploadStatus = document.getElementById("upload-status");
const resultList = document.getElementById("upload-result");
const contentStatus = document.getElementById("content-status");
const contentList = document.getElementById("content-list");
const refreshButton = document.getElementById("content-refresh");

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const file = fileInput.files[0];
  if (!file) {
    showStatus(uploadStatus, "Choose a PDF before uploading.", "error");
    return;
  }

  if (!file.name.toLowerCase().endsWith(".pdf")) {
    showStatus(uploadStatus, "Upload a PDF file.", "error");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  submitButton.disabled = true;
  resultList.classList.add("hidden");
  resultList.replaceChildren();
  showStatus(uploadStatus, "Uploading PDF...", "loading");

  try {
    const response = await fetch("/api/content/upload-pdf", {
      method: "POST",
      body: formData,
    });
    const result = await response.json();

    if (!response.ok) {
      showStatus(uploadStatus, result.error || "Upload failed.", "error");
      renderResult(result);
      return;
    }

    uploadForm.reset();
    showStatus(uploadStatus, "PDF uploaded to Pinecone.", "success");
    renderResult(result);
    await loadContentItems();
  } catch (error) {
    console.error("Upload failed:", error);
    showStatus(
      uploadStatus,
      "Upload failed. Check that the server is still running.",
      "error",
    );
  } finally {
    submitButton.disabled = false;
  }
});

refreshButton.addEventListener("click", () => {
  loadContentItems();
});

contentList.addEventListener("click", async (event) => {
  const deleteButton = event.target.closest("[data-delete-document-id]");
  if (!deleteButton) {
    return;
  }

  const documentId = deleteButton.dataset.deleteDocumentId;
  const filename = deleteButton.dataset.filename || "this PDF";
  const confirmed = window.confirm(`Delete "${filename}" from uploaded content?`);
  if (!confirmed) {
    return;
  }

  deleteButton.disabled = true;
  showStatus(contentStatus, "Deleting content...", "loading");

  try {
    const response = await fetch(`/api/content/${documentId}`, {
      method: "DELETE",
    });
    const result = await response.json();

    if (!response.ok) {
      showStatus(contentStatus, result.error || "Delete failed.", "error");
      deleteButton.disabled = false;
      return;
    }

    showStatus(
      contentStatus,
      result.warning || "Content deleted.",
      "success",
    );
    await loadContentItems({ keepStatus: true });
  } catch (error) {
    console.error("Delete failed:", error);
    showStatus(
      contentStatus,
      "Delete failed. Check that the server is still running.",
      "error",
    );
    deleteButton.disabled = false;
  }
});

loadContentItems();

async function loadContentItems(options = {}) {
  if (!options.keepStatus) {
    showStatus(contentStatus, "Loading uploaded content...", "loading");
  }
  refreshButton.disabled = true;

  try {
    const response = await fetch("/api/content");
    const result = await response.json();

    if (!response.ok) {
      showStatus(contentStatus, result.error || "Could not load content.", "error");
      contentList.replaceChildren();
      return;
    }

    renderContentItems(result.items || []);
    if (!options.keepStatus) {
      hideStatus(contentStatus);
    }
  } catch (error) {
    console.error("Could not load content:", error);
    showStatus(
      contentStatus,
      "Could not load uploaded content. Check that the server is still running.",
      "error",
    );
    contentList.replaceChildren();
  } finally {
    refreshButton.disabled = false;
  }
}

function showStatus(element, message, type) {
  element.textContent = message;
  element.className = `upload-status ${type}`;
}

function hideStatus(element) {
  element.textContent = "";
  element.className = "upload-status hidden";
}

function renderResult(result) {
  const fields = [
    ["Filename", result.filename],
    ["Document ID", result.documentId],
    ["Chunks", result.chunkCount],
    ["Index", result.indexName],
    ["Namespace", result.namespace],
    ["Saved path", result.savedPath],
  ];

  const visibleFields = fields.filter(([, value]) => value !== undefined && value !== null);
  if (!visibleFields.length) {
    resultList.classList.add("hidden");
    return;
  }

  resultList.replaceChildren();
  for (const [label, value] of visibleFields) {
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value;
    resultList.append(term, detail);
  }
  resultList.classList.remove("hidden");
}

function renderContentItems(items) {
  contentList.replaceChildren();

  if (!items.length) {
    const emptyState = document.createElement("p");
    emptyState.className = "content-empty";
    emptyState.textContent = "No uploaded PDFs yet.";
    contentList.append(emptyState);
    return;
  }

  for (const item of items) {
    const contentItem = document.createElement("article");
    contentItem.className = "content-item";

    const details = document.createElement("div");
    details.className = "content-item-details";

    const title = document.createElement("h3");
    title.textContent = item.filename || item.documentId;

    const meta = document.createElement("dl");
    meta.className = "content-meta";
    appendMeta(meta, "Uploaded", formatDate(item.uploadedAt));
    appendMeta(meta, "Size", formatBytes(item.sizeBytes));
    appendMeta(meta, "Chunks", item.chunkCount ?? "Unknown");
    appendMeta(meta, "Status", formatStatus(item.status));
    appendMeta(meta, "Document ID", item.documentId);

    details.append(title, meta);

    const deleteButton = document.createElement("button");
    deleteButton.className = "btn danger content-delete";
    deleteButton.type = "button";
    deleteButton.textContent = "Delete";
    deleteButton.dataset.deleteDocumentId = item.documentId;
    deleteButton.dataset.filename = item.filename || item.documentId;

    contentItem.append(details, deleteButton);
    contentList.append(contentItem);
  }
}

function appendMeta(list, label, value) {
  if (value === undefined || value === null || value === "") {
    return;
  }

  const term = document.createElement("dt");
  term.textContent = label;
  const detail = document.createElement("dd");
  detail.textContent = value;
  list.append(term, detail);
}

function formatDate(value) {
  if (!value) {
    return "Unknown";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatBytes(value) {
  if (!Number.isFinite(value)) {
    return "Unknown";
  }

  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: 1,
    style: "unit",
    unit: "megabyte",
  }).format(value / 1024 / 1024);
}

function formatStatus(value) {
  const status = value || "local";
  return status.charAt(0).toUpperCase() + status.slice(1);
}
