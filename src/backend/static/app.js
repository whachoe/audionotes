// Vanilla JS voice recording for the web frontend (Phase 3.2) - mirrors the
// Android app's record/stop button, using the browser's own mic access
// (getUserMedia/MediaRecorder) and uploading straight to the same
// POST /api/notes the mobile app uses (cookie auth works there too, see
// auth.py's require_user).
(function () {
  const btn = document.getElementById("record-btn");
  if (!btn) return; // not on this page

  const timerEl = document.getElementById("record-timer");
  const errorEl = document.getElementById("record-error");

  let mediaRecorder = null;
  let chunks = [];
  let startedAt = 0;
  let timerInterval = null;

  function formatElapsed(ms) {
    const totalSeconds = Math.floor(ms / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return minutes + ":" + String(seconds).padStart(2, "0");
  }

  function setIdle() {
    btn.dataset.state = "idle";
    btn.textContent = "Start Recording";
    timerEl.textContent = "";
    clearInterval(timerInterval);
  }

  function setRecording() {
    btn.dataset.state = "recording";
    btn.textContent = "Stop Recording";
    startedAt = Date.now();
    timerInterval = setInterval(() => {
      timerEl.textContent = formatElapsed(Date.now() - startedAt);
    }, 250);
  }

  async function startRecording() {
    errorEl.textContent = "";
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      errorEl.textContent = "Couldn't access the microphone: " + err.message;
      return;
    }

    chunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    mediaRecorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      uploadRecording();
    };
    mediaRecorder.start();
    setRecording();
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }
    setIdle();
  }

  async function uploadRecording() {
    if (chunks.length === 0) return;
    const mimeType = mediaRecorder.mimeType || "audio/webm";
    const blob = new Blob(chunks, { type: mimeType });
    const extension = mimeType.includes("ogg") ? "ogg" : "webm";
    const formData = new FormData();
    formData.append("file", blob, "recording." + extension);

    btn.disabled = true;
    errorEl.textContent = "Uploading…";
    try {
      const response = await fetch("/api/notes", {
        method: "POST",
        body: formData,
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new Error("Upload failed (" + response.status + ")");
      }
      window.location.reload();
    } catch (err) {
      errorEl.textContent = err.message;
      btn.disabled = false;
    }
  }

  btn.addEventListener("click", () => {
    if (btn.dataset.state === "recording") {
      stopRecording();
    } else {
      startRecording();
    }
  });
})();
