// --- Main Application Logic ---

const statusDiv = document.getElementById("status");
const authSection = document.getElementById("auth-section");
const appSection = document.getElementById("app-section");
const sessionEndSection = document.getElementById("session-end-section");
const sessionEndMessage = document.getElementById("session-end-message");
const restartBtn = document.getElementById("restartBtn");
const micBtn = document.getElementById("micBtn");
const cameraBtn = document.getElementById("cameraBtn");
const screenBtn = document.getElementById("screenBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const textInput = document.getElementById("textInput");
const sendBtn = document.getElementById("sendBtn");
const videoPreview = document.getElementById("video-preview");
const videoPlaceholder = document.getElementById("video-placeholder");
const connectBtn = document.getElementById("connectBtn");
const topicInput = document.getElementById("topicInput");
const canvasUrlInput = document.getElementById("canvasUrl");
const canvasTokenInput = document.getElementById("canvasToken");
const topicError = document.getElementById("topic-error");
const chatLog = document.getElementById("chat-log");
const logoutBtn = document.getElementById("logoutBtn");
const curriculumPanel = document.getElementById("curriculum-panel");
const curriculumEmpty = document.getElementById("curriculum-empty");
const curriculumGoal = document.getElementById("curriculum-goal");
const curriculumDuration = document.getElementById("curriculum-duration");
const curriculumSteps = document.getElementById("curriculum-steps");

let currentGeminiMessageDiv = null;
let currentUserMessageDiv = null;
let lastErrorMessage = "";
let currentCurriculum = null;
let pendingSessionTopic = "";
let pendingCanvasUrl = "";
let pendingCanvasToken = "";
const completedCurriculumSteps = new Set();

const mediaHandler = new MediaHandler();
const geminiClient = new GeminiClient({
  onOpen: () => {
    statusDiv.textContent = "Planning...";
    statusDiv.className = "status connected";
    authSection.classList.add("hidden");
    appSection.classList.remove("hidden");
    geminiClient.startSession(pendingSessionTopic, pendingCanvasUrl, pendingCanvasToken);
  },
  onMessage: (event) => {
    if (typeof event.data === "string") {
      try {
        const msg = JSON.parse(event.data);
        handleJsonMessage(msg);
      } catch (e) {
        console.error("Parse error:", e);
      }
    } else {
      mediaHandler.playAudio(event.data);
    }
  },
  onClose: (e) => {
    console.log("WS Closed:", e);
    if (lastErrorMessage) {
      statusDiv.textContent = "Connection Error";
      statusDiv.className = "status error";
    } else {
      statusDiv.textContent = "Disconnected";
      statusDiv.className = "status disconnected";
    }
    showSessionEnd();
  },
  onError: (e) => {
    console.error("WS Error:", e);
    statusDiv.textContent = "Connection Error";
    statusDiv.className = "status error";
  },
});

async function requireTutorAuth() {
  try {
    const response = await fetch("/auth/me");
    const result = await response.json();
    if (!result.authenticated) {
      window.location.href = "/";
    }
  } catch (error) {
    console.error("Could not check auth state:", error);
    window.location.href = "/";
  }
}

function handleJsonMessage(msg) {
  if (msg.type === "error") {
    lastErrorMessage = msg.error || "An unknown Gemini API error occurred.";
    statusDiv.textContent = "Connection Error";
    statusDiv.className = "status error";
    appendMessage("error", lastErrorMessage);
  } else if (msg.type === "interrupted") {
    mediaHandler.stopAudioPlayback();
    currentGeminiMessageDiv = null;
    currentUserMessageDiv = null;
  } else if (msg.type === "turn_complete") {
    currentGeminiMessageDiv = null;
    currentUserMessageDiv = null;
  } else if (msg.type === "curriculum") {
    renderCurriculum(msg.curriculum);
  } else if (msg.type === "tool_call") {
    handleToolCall(msg);
  } else if (msg.type === "user") {
    if (currentUserMessageDiv) {
      currentUserMessageDiv.textContent += msg.text;
      chatLog.scrollTop = chatLog.scrollHeight;
    } else {
      currentUserMessageDiv = appendMessage("user", msg.text);
    }
  } else if (msg.type === "gemini") {
    if (currentGeminiMessageDiv) {
      currentGeminiMessageDiv.textContent += msg.text;
      chatLog.scrollTop = chatLog.scrollHeight;
    } else {
      currentGeminiMessageDiv = appendMessage("gemini", msg.text);
    }
  }
}

function appendMessage(type, text) {
  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${type}`;
  msgDiv.textContent = text;
  chatLog.appendChild(msgDiv);
  chatLog.scrollTop = chatLog.scrollHeight;
  return msgDiv;
}

function renderCurriculum(curriculum) {
  if (!curriculum || !Array.isArray(curriculum.steps)) return;

  currentCurriculum = curriculum;
  completedCurriculumSteps.clear();
  statusDiv.textContent = "Connected";
  statusDiv.className = "status connected";
  curriculumPanel.classList.remove("hidden");
  curriculumEmpty.classList.add("hidden");
  curriculumGoal.textContent = curriculum.session_goal || "";
  curriculumDuration.textContent = curriculum.estimated_minutes
    ? `${curriculum.estimated_minutes} min`
    : "";

  curriculumSteps.innerHTML = "";
  curriculum.steps.forEach((step, index) => {
    const item = document.createElement("li");
    item.className = index === 0 ? "current" : "";
    item.dataset.stepOrder = String(step.order);

    const status = document.createElement("span");
    status.className = "step-status";
    status.textContent = index === 0 ? "•" : "";

    const text = document.createElement("span");
    text.className = "step-text";
    text.textContent = step.title;

    item.append(status, text);
    curriculumSteps.appendChild(item);
  });
}

function handleToolCall(msg) {
  if (msg.name !== "mark_curriculum_step_complete") return;

  const stepOrder = Number(msg.args?.step_order || msg.result?.step_order);
  if (!Number.isInteger(stepOrder)) return;

  markCurriculumStepComplete(stepOrder);
}

function markCurriculumStepComplete(stepOrder) {
  completedCurriculumSteps.add(stepOrder);

  const items = [...curriculumSteps.querySelectorAll("li")];
  items.forEach((item) => {
    const itemStepOrder = Number(item.dataset.stepOrder);
    const status = item.querySelector(".step-status");

    item.classList.toggle("complete", completedCurriculumSteps.has(itemStepOrder));
    if (completedCurriculumSteps.has(itemStepOrder)) {
      status.textContent = "\u2713";
    }
    item.classList.remove("current");
  });

  const nextItem = items.find((item) => {
    return !completedCurriculumSteps.has(Number(item.dataset.stepOrder));
  });
  if (nextItem) {
    nextItem.classList.add("current");
    const status = nextItem.querySelector(".step-status");
    if (status && !status.textContent) status.textContent = "•";
  }
}

// Connect Button Handler
connectBtn.onclick = async () => {
  const topic = topicInput.value.trim();
  const canvasUrl = canvasUrlInput.value.trim();
  const canvasToken = canvasTokenInput.value.trim();
  if (!topic) {
    topicError.textContent = "Enter a topic from your uploaded course content.";
    topicError.classList.remove("hidden");
    statusDiv.textContent = "Topic Required";
    statusDiv.className = "status error";
    topicInput.focus();
    return;
  }

  pendingSessionTopic = topic;
  pendingCanvasUrl = canvasUrl;
  pendingCanvasToken = canvasToken;
  topicError.textContent = "";
  topicError.classList.add("hidden");
  statusDiv.textContent = "Connecting...";
  connectBtn.disabled = true;

  try {
    // Initialize audio context on user gesture
    await mediaHandler.initializeAudio();

    geminiClient.connect();
  } catch (error) {
    console.error("Connection error:", error);
    statusDiv.textContent = "Connection Failed: " + error.message;
    statusDiv.className = "status error";
    connectBtn.disabled = false;
  }
};

topicInput.onkeypress = (e) => {
  if (e.key === "Enter") connectBtn.click();
};

// UI Controls
disconnectBtn.onclick = () => {
  geminiClient.disconnect();
};

micBtn.onclick = async () => {
  if (mediaHandler.isRecording) {
    mediaHandler.stopAudio();
    micBtn.textContent = "Start Mic";
  } else {
    try {
      await mediaHandler.startAudio((data) => {
        if (geminiClient.isConnected()) {
          geminiClient.send(data);
        }
      });
      micBtn.textContent = "Stop Mic";
    } catch (e) {
      alert("Could not start audio capture");
    }
  }
};

cameraBtn.onclick = async () => {
  if (cameraBtn.textContent === "Stop Camera") {
    mediaHandler.stopVideo(videoPreview);
    cameraBtn.textContent = "Start Camera";
    screenBtn.textContent = "Share Screen";
    videoPlaceholder.classList.remove("hidden");
  } else {
    // If another stream is active (e.g. Screen), stop it first
    if (mediaHandler.videoStream) {
      mediaHandler.stopVideo(videoPreview);
      screenBtn.textContent = "Share Screen";
    }

    try {
      await mediaHandler.startVideo(videoPreview, (base64Data) => {
        if (geminiClient.isConnected()) {
          geminiClient.sendImage(base64Data);
        }
      });
      cameraBtn.textContent = "Stop Camera";
      screenBtn.textContent = "Share Screen";
      videoPlaceholder.classList.add("hidden");
    } catch (e) {
      alert("Could not access camera");
    }
  }
};

screenBtn.onclick = async () => {
  if (screenBtn.textContent === "Stop Sharing") {
    mediaHandler.stopVideo(videoPreview);
    screenBtn.textContent = "Share Screen";
    cameraBtn.textContent = "Start Camera";
    videoPlaceholder.classList.remove("hidden");
  } else {
    // If another stream is active (e.g. Camera), stop it first
    if (mediaHandler.videoStream) {
      mediaHandler.stopVideo(videoPreview);
      cameraBtn.textContent = "Start Camera";
    }

    try {
      await mediaHandler.startScreen(
        videoPreview,
        (base64Data) => {
          if (geminiClient.isConnected()) {
            geminiClient.sendImage(base64Data);
          }
        },
        () => {
          // onEnded callback (e.g. user stopped sharing from browser)
          screenBtn.textContent = "Share Screen";
          videoPlaceholder.classList.remove("hidden");
        }
      );
      screenBtn.textContent = "Stop Sharing";
      cameraBtn.textContent = "Start Camera";
      videoPlaceholder.classList.add("hidden");
    } catch (e) {
      alert("Could not share screen");
    }
  }
};

sendBtn.onclick = sendText;
textInput.onkeypress = (e) => {
  if (e.key === "Enter") sendText();
};

function sendText() {
  const text = textInput.value;
  if (text && geminiClient.isConnected()) {
    geminiClient.sendText(text);
    appendMessage("user", text);
    textInput.value = "";
  }
}

function resetUI() {
  authSection.classList.remove("hidden");
  appSection.classList.add("hidden");
  sessionEndSection.classList.add("hidden");

  mediaHandler.stopAudio();
  mediaHandler.stopVideo(videoPreview);
  videoPlaceholder.classList.remove("hidden");

  micBtn.textContent = "Start Mic";
  cameraBtn.textContent = "Start Camera";
  screenBtn.textContent = "Share Screen";
  chatLog.innerHTML = "";
  currentCurriculum = null;
  pendingSessionTopic = "";
  completedCurriculumSteps.clear();
  curriculumPanel.classList.add("hidden");
  curriculumEmpty.classList.remove("hidden");
  curriculumGoal.textContent = "";
  curriculumDuration.textContent = "";
  curriculumSteps.innerHTML = "";
  topicError.textContent = "";
  topicError.classList.add("hidden");
  lastErrorMessage = "";
  sessionEndMessage.textContent = "";
  sessionEndMessage.classList.add("hidden");
  connectBtn.disabled = false;
}

function showSessionEnd() {
  appSection.classList.add("hidden");
  sessionEndSection.classList.remove("hidden");
  sessionEndMessage.textContent = lastErrorMessage;
  sessionEndMessage.classList.toggle("hidden", !lastErrorMessage);
  mediaHandler.stopAudio();
  mediaHandler.stopVideo(videoPreview);
}

restartBtn.onclick = () => {
  resetUI();
};

logoutBtn.onclick = async () => {
  geminiClient.disconnect();
  resetUI();

  try {
    await fetch("/auth/logout", { method: "POST" });
  } catch (error) {
    console.error("Logout error:", error);
  } finally {
    window.location.href = "/";
  }
};

requireTutorAuth();
