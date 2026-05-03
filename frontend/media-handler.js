/**
 * MediaHandler: Manages Audio/Video capture and playback
 */
class MediaHandler {
  constructor() {
    this.audioContext = null;
    this.mediaStream = null;
    this.audioWorkletNode = null;
    this.videoStream = null;
    this.videoInterval = null;
    this.nextStartTime = 0;
    this.scheduledSources = [];
    this.isRecording = false;
    this.videoCanvas = document.createElement("canvas");
    this.canvasCtx = this.videoCanvas.getContext("2d");
  }

  async initializeAudio() {
    if (!window.AudioContext && !window.webkitAudioContext) {
      throw new Error("This browser does not support audio capture.");
    }

    if (!this.audioContext) {
      this.audioContext = new (window.AudioContext ||
        window.webkitAudioContext)();
      if (!this.audioContext.audioWorklet) {
        throw new Error(
          "Audio worklets are unavailable. Open the app from http://localhost:8001 in a modern browser."
        );
      }
      await this.audioContext.audioWorklet.addModule(
        "/static/pcm-processor.js"
      );
    }
    if (this.audioContext.state === "suspended") {
      await this.audioContext.resume();
    }
  }

  async startAudio(onAudioData) {
    await this.initializeAudio();

    try {
      const mediaDevices = this.getMediaDevices();
      this.mediaStream = await mediaDevices.getUserMedia({
        audio: true,
      });
      const source = this.audioContext.createMediaStreamSource(
        this.mediaStream
      );
      this.audioWorkletNode = new AudioWorkletNode(
        this.audioContext,
        "pcm-processor"
      );

      this.audioWorkletNode.port.onmessage = (event) => {
        if (this.isRecording) {
          const downsampled = this.downsampleBuffer(
            event.data,
            this.audioContext.sampleRate,
            16000
          );
          const pcm16 = this.convertFloat32ToInt16(downsampled);
          onAudioData(pcm16);
        }
      };

      source.connect(this.audioWorkletNode);
      // Mute local feedback
      const muteGain = this.audioContext.createGain();
      muteGain.gain.value = 0;
      this.audioWorkletNode.connect(muteGain);
      muteGain.connect(this.audioContext.destination);

      this.isRecording = true;
    } catch (e) {
      console.error("Error starting audio:", e);
      throw this.describeMediaError(e, "microphone");
    }
  }

  stopAudio() {
    this.isRecording = false;
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
    }
    if (this.audioWorkletNode) {
      this.audioWorkletNode.disconnect();
      this.audioWorkletNode = null;
    }
  }

  async startVideo(videoElement, onFrame) {
    try {
      const mediaDevices = this.getMediaDevices();
      this.videoStream = await mediaDevices.getUserMedia({
        video: true,
      });
      videoElement.srcObject = this.videoStream;

      this.videoInterval = setInterval(() => {
        this.captureFrame(videoElement, onFrame);
      }, 1000); // 1 FPS
    } catch (e) {
      console.error("Error starting video:", e);
      throw this.describeMediaError(e, "camera");
    }
  }

  async startScreen(videoElement, onFrame, onEnded) {
    try {
      const mediaDevices = this.getMediaDevices();
      if (!mediaDevices.getDisplayMedia) {
        throw new Error("This browser does not support screen sharing.");
      }
      this.videoStream = await mediaDevices.getDisplayMedia({
        video: true,
      });
      videoElement.srcObject = this.videoStream;

      // Handle stream ending (e.g. user clicks "Stop sharing" in browser UI)
      this.videoStream.getVideoTracks()[0].onended = () => {
        this.stopVideo(videoElement);
        if (onEnded) onEnded();
      };

      this.videoInterval = setInterval(() => {
        this.captureFrame(videoElement, onFrame);
      }, 1000); // 1 FPS
    } catch (e) {
      console.error("Error starting screen share:", e);
      throw this.describeMediaError(e, "screen");
    }
  }

  stopVideo(videoElement) {
    if (this.videoStream) {
      this.videoStream.getTracks().forEach((t) => t.stop());
      this.videoStream = null;
    }
    if (this.videoInterval) {
      clearInterval(this.videoInterval);
      this.videoInterval = null;
    }
    if (videoElement) {
      videoElement.srcObject = null;
    }
  }

  captureFrame(videoElement, onFrame) {
    if (!this.videoStream) return;
    this.videoCanvas.width = 640;
    this.videoCanvas.height = 480;
    this.canvasCtx.drawImage(videoElement, 0, 0, 640, 480);
    const base64 = this.videoCanvas.toDataURL("image/jpeg", 0.7).split(",")[1];
    onFrame(base64);
  }

  playAudio(arrayBuffer) {
    if (!this.audioContext) return;
    if (this.audioContext.state === "suspended") {
      this.audioContext.resume();
    }

    const pcmData = new Int16Array(arrayBuffer);
    const float32Data = new Float32Array(pcmData.length);
    for (let i = 0; i < pcmData.length; i++) {
      float32Data[i] = pcmData[i] / 32768.0;
    }

    const buffer = this.audioContext.createBuffer(1, float32Data.length, 24000);
    buffer.getChannelData(0).set(float32Data);

    const source = this.audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(this.audioContext.destination);

    const now = this.audioContext.currentTime;
    this.nextStartTime = Math.max(now, this.nextStartTime);
    source.start(this.nextStartTime);
    this.nextStartTime += buffer.duration;

    this.scheduledSources.push(source);
    source.onended = () => {
      const idx = this.scheduledSources.indexOf(source);
      if (idx > -1) this.scheduledSources.splice(idx, 1);
    };
  }

  stopAudioPlayback() {
    this.scheduledSources.forEach((s) => {
      try {
        s.stop();
      } catch (e) {}
    });
    this.scheduledSources = [];
    if (this.audioContext) {
      this.nextStartTime = this.audioContext.currentTime;
    }
  }

  getMediaDevices() {
    if (!window.isSecureContext) {
      throw new Error(
        "Camera and microphone need a secure page. Use http://localhost:8001 locally or HTTPS when hosted."
      );
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error(
        "This browser does not expose camera or microphone access on this page."
      );
    }

    return navigator.mediaDevices;
  }

  describeMediaError(error, deviceName) {
    if (error instanceof Error && error.message) {
      if (
        !error.name ||
        error.name === "Error" ||
        error.message.startsWith("Camera and microphone") ||
        error.message.startsWith("This browser")
      ) {
        return error;
      }
    }

    const messages = {
      NotAllowedError: `The browser blocked ${deviceName} access. Allow it in the site permissions and in system privacy settings.`,
      PermissionDeniedError: `The browser blocked ${deviceName} access. Allow it in the site permissions and in system privacy settings.`,
      NotFoundError: `No ${deviceName} was found. Check that one is connected and enabled.`,
      DevicesNotFoundError: `No ${deviceName} was found. Check that one is connected and enabled.`,
      NotReadableError: `The ${deviceName} is already in use or the system blocked access to it.`,
      TrackStartError: `The ${deviceName} is already in use or the system blocked access to it.`,
      SecurityError: `${deviceName} access is blocked on this page. Use http://localhost:8001 locally or HTTPS when hosted.`,
      AbortError: `${deviceName} access failed before it could start. Try again after closing other apps using it.`,
      OverconstrainedError: `The requested ${deviceName} settings are not available on this device.`,
    };

    return new Error(
      messages[error.name] ||
        error.message ||
        `Could not start ${deviceName} access.`
    );
  }

  // Utils
  downsampleBuffer(buffer, sampleRate, outSampleRate) {
    if (outSampleRate === sampleRate) return buffer;
    const ratio = sampleRate / outSampleRate;
    const newLength = Math.round(buffer.length / ratio);
    const result = new Float32Array(newLength);
    let offsetResult = 0;
    let offsetBuffer = 0;
    while (offsetResult < result.length) {
      const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
      let accum = 0,
        count = 0;
      for (
        let i = offsetBuffer;
        i < nextOffsetBuffer && i < buffer.length;
        i++
      ) {
        accum += buffer[i];
        count++;
      }
      result[offsetResult] = accum / count;
      offsetResult++;
      offsetBuffer = nextOffsetBuffer;
    }
    return result;
  }

  convertFloat32ToInt16(buffer) {
    let l = buffer.length;
    const buf = new Int16Array(l);
    while (l--) {
      buf[l] = Math.min(1, Math.max(-1, buffer[l])) * 0x7fff;
    }
    return buf.buffer;
  }
}
