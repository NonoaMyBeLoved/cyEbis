const uploadView = document.querySelector("#upload-view");
const previewView = document.querySelector("#preview-view");
const fileInput = document.querySelector("#file-input");
const fileName = document.querySelector("#file-name");
const processButton = document.querySelector("#process-button");
const backUploadButton = document.querySelector("#back-upload-button");
const downloadMixButton = document.querySelector("#download-mix-button");
const deviceStatus = document.querySelector("#device-status");
const uploadProgress = document.querySelector("#upload-progress");
const statusTitle = document.querySelector("#status-title");
const statusCopy = document.querySelector("#status-copy");
const message = document.querySelector("#message");
const percent = document.querySelector("#percent");
const progressFill = document.querySelector("#progress-fill");
const trackStack = document.querySelector("#track-stack");
const playToggle = document.querySelector("#play-toggle");
const currentTimeLabel = document.querySelector("#current-time");
const durationLabel = document.querySelector("#duration");

const VOLUME_MUTE_THRESHOLD = 0.03;

const stemLabels = {
  guitar: "기타",
  bass: "베이스",
  drums: "드럼",
  vocals: "보컬",
  synth_other: "신스/기타",
};

const stemDescriptions = {
  guitar: "기타 파트",
  bass: "베이스 파트",
  drums: "드럼 파트",
  vocals: "보컬 파트",
  synth_other: "신스, 피아노, 기타 잔여 파트",
};

const defaultFileNameText = "음악 파일을 선택하세요";
const defaultStatusTitle = "Stem을 조절하고 원하는 믹스를 만드세요.";
const defaultStatusCopy = "볼륨, mute, solo 상태는 믹스 다운로드에 반영됩니다.";

let currentFile = null;
let currentJob = null;
let currentTime = 0;
let duration = 0;
let isPlaying = false;
let soloStem = null;
let timer = null;
let renderedJobId = null;
let deviceInfo = null;

loadDeviceInfo();

fileInput.addEventListener("change", () => {
  currentFile = fileInput.files?.[0] ?? null;
  fileName.textContent = currentFile ? currentFile.name : defaultFileNameText;
  processButton.disabled = !currentFile;
});

document.querySelectorAll('input[name="device"]').forEach((input) => {
  input.addEventListener("change", renderDeviceStatus);
});

processButton.addEventListener("click", async () => {
  if (!currentFile) return;

  processButton.disabled = true;
  uploadProgress.classList.remove("hidden");
  setProgress("파일을 업로드하는 중입니다.", 0.05);

  const form = new FormData();
  form.append("file", currentFile);
  form.append("device", selectedDevice());

  try {
    const response = await fetch("/api/jobs", { method: "POST", body: form });
    if (!response.ok) throw new Error(await response.text());
    const payload = await response.json();
    poll(payload.id);
  } catch (error) {
    setProgress(error instanceof Error ? error.message : "업로드를 시작하지 못했습니다.", 1);
    processButton.disabled = false;
  }
});

backUploadButton.addEventListener("click", resetToUpload);

downloadMixButton.addEventListener("click", async () => {
  if (!currentJob) return;

  const originalText = downloadMixButton.textContent;
  downloadMixButton.disabled = true;
  downloadMixButton.textContent = "믹스 생성 중";

  try {
    const response = await fetch(`/api/jobs/${currentJob.id}/mix`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectMixState()),
    });
    if (!response.ok) throw new Error(await response.text());

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${safeFileName(currentJob?.source_name ?? "cyEbis")}-cymixed.mp3`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    console.error(error);
  } finally {
    downloadMixButton.disabled = false;
    downloadMixButton.textContent = originalText;
  }
});

playToggle.addEventListener("click", () => {
  if (isPlaying) {
    pauseAll();
  } else {
    playAll();
  }
});

window.addEventListener("resize", updatePlayhead);

const initialJobId = new URLSearchParams(window.location.search).get("job");
if (initialJobId) {
  poll(initialJobId);
}

function resetToUpload() {
  pauseAll();
  fileInput.value = "";
  currentFile = null;
  currentJob = null;
  renderedJobId = null;
  soloStem = null;
  currentTime = 0;
  duration = 0;
  fileName.textContent = defaultFileNameText;
  processButton.disabled = true;
  downloadMixButton.disabled = true;
  uploadProgress.classList.add("hidden");
  previewView.classList.add("hidden");
  uploadView.classList.remove("hidden");
  window.history.replaceState(null, "", "/");
}

async function loadDeviceInfo() {
  try {
    const response = await fetch("/api/devices");
    if (!response.ok) throw new Error(await response.text());
    deviceInfo = await response.json();
  } catch {
    deviceInfo = null;
  }
  renderDeviceStatus();
}

function renderDeviceStatus() {
  if (!deviceStatus) return;

  const selected = selectedDevice();
  const torchVersion = deviceInfo?.torch_version ?? "알 수 없음";

  if (!deviceInfo) {
    deviceStatus.textContent = "장치 정보를 가져오지 못했습니다. 자동 모드로 시작하면 가능한 장치를 사용합니다.";
    return;
  }

  if (deviceInfo.cuda_available) {
    const name = deviceInfo.device_name ? ` (${deviceInfo.device_name})` : "";
    deviceStatus.textContent = `CUDA 사용 가능${name}. GPU 모드에서 Demucs를 실행할 수 있습니다.`;
    return;
  }

  if (selected === "cuda") {
    deviceStatus.textContent = `CUDA를 사용할 수 없어 처리 중 CPU로 대체됩니다. torch=${torchVersion}`;
  } else {
    deviceStatus.textContent = `현재는 CPU로 처리됩니다. GPU를 쓰려면 CUDA 지원 PyTorch가 필요합니다. torch=${torchVersion}`;
  }
}

async function poll(jobId) {
  const response = await fetch(`/api/jobs/${jobId}`);
  if (!response.ok) {
    setProgress(await response.text(), 1);
    return;
  }

  const job = await response.json();
  currentJob = job;
  setProgress(progressMessage(job), job.progress);

  if (job.status === "complete") {
    window.history.replaceState(null, "", `?job=${job.id}`);
    uploadView.classList.add("hidden");
    previewView.classList.remove("hidden");
    processButton.disabled = false;
    downloadMixButton.disabled = false;
    statusTitle.textContent = defaultStatusTitle;
    statusCopy.textContent = defaultStatusCopy;
    await renderTracks(job);
    return;
  }

  if (job.status === "failed") {
    processButton.disabled = false;
    setProgress("분리에 실패했습니다.", 1);
    return;
  }

  window.setTimeout(() => poll(jobId), 1200);
}

function setProgress(text, value) {
  message.textContent = text;
  percent.textContent = `${Math.round(value * 100)}%`;
  progressFill.style.width = `${value * 100}%`;
}

async function renderTracks(job) {
  if (renderedJobId === job.id) return;

  renderedJobId = job.id;
  soloStem = null;
  trackStack.innerHTML = '<div id="global-playhead" class="global-playhead hidden"></div>';

  const stems = orderStems(job.stems);
  duration = Math.max(...stems.map((stem) => stem.duration || 0), 0.1);
  currentTime = 0;
  currentTimeLabel.textContent = formatTime(0);
  durationLabel.textContent = `/ ${formatTime(duration)}`;

  for (const stem of stems) {
    const row = document.createElement("article");
    row.className = stem.active ? "track-row" : "track-row disabled";
    row.dataset.stem = stem.name;
    row.innerHTML = `
      <div class="track-label">
        <strong>${displayStemLabel(stem.name)}</strong>
        <span>${stem.active ? readableStemName(stem.name) : "감지된 신호가 약해 비활성화했습니다."}</span>
      </div>
      <button class="wave-shell" type="button" ${stem.active ? "" : "disabled"}>
        <canvas width="760" height="92"></canvas>
        <audio data-stem="${stem.name}" src="${stem.url}" preload="auto"></audio>
      </button>
      <div class="volume-strip">
        <button class="icon-button mute" type="button" ${stem.active ? "" : "disabled"} aria-label="음소거">🔈</button>
        <input class="vertical-volume" type="range" min="0" max="1" step="0.01" value="${stem.active ? "1" : "0"}" ${stem.active ? "" : "disabled"} />
        <span class="volume-number">${stem.active ? "100" : "0"}</span>
      </div>
      <div class="track-actions">
        <button class="solo-button" type="button" ${stem.active ? "" : "disabled"}>Solo</button>
        <button class="tab-button disabled" type="button" disabled>
          <span>탭 추출</span>
          <small>비활성화</small>
        </button>
      </div>
      <div class="tab-results"></div>
    `;
    trackStack.append(row);
    wireTrack(row, stem);

    try {
      const waveform = stem.active
        ? await fetch(stem.waveform_url).then((waveResponse) => waveResponse.json())
        : { peaks: [] };
      drawWaveform(row.querySelector("canvas"), waveform.peaks, stem.active);
    } catch {
      drawWaveform(row.querySelector("canvas"), [], stem.active);
    }
  }

  updateAudioState();
  updatePlayhead();
}

function wireTrack(row, stem) {
  const audio = row.querySelector("audio");
  const wave = row.querySelector(".wave-shell");
  const volume = row.querySelector(".vertical-volume");
  const volumeNumber = row.querySelector(".volume-number");
  const mute = row.querySelector(".mute");
  const solo = row.querySelector(".solo-button");

  audio.volume = stem.active ? 1 : 0;
  audio.muted = !stem.active;
  audio.dataset.userMuted = stem.active ? "false" : "true";
  volume.draggable = false;

  wave.addEventListener("click", (event) => {
    if (!stem.active) return;
    const rect = wave.getBoundingClientRect();
    seekTo(((event.clientX - rect.left) / rect.width) * duration);
  });

  volume.addEventListener("pointerdown", (event) => {
    volume.setPointerCapture?.(event.pointerId);
  });

  volume.addEventListener("dragstart", (event) => {
    event.preventDefault();
  });

  volume.addEventListener("input", () => {
    const value = Number(volume.value);
    audio.volume = value;
    audio.dataset.userMuted = value < VOLUME_MUTE_THRESHOLD ? "true" : "false";
    volumeNumber.textContent = Math.round(value * 100);
    mute.textContent = value < VOLUME_MUTE_THRESHOLD ? "🔇" : "🔈";
    updateAudioState();
  });

  mute.addEventListener("click", () => {
    const willMute = audio.dataset.userMuted !== "true";
    audio.dataset.userMuted = String(willMute);
    volume.value = willMute ? "0" : "1";
    audio.volume = willMute ? 0 : 1;
    volumeNumber.textContent = willMute ? "0" : "100";
    mute.textContent = willMute ? "🔇" : "🔈";
    updateAudioState();
  });

  solo.addEventListener("click", () => {
    soloStem = soloStem === stem.name ? null : stem.name;
    document.querySelectorAll(".solo-button").forEach((button) => button.classList.remove("active"));
    if (soloStem === stem.name) solo.classList.add("active");
    updateAudioState();
  });
}

function playAll() {
  pauseAll(false);

  const audios = playbackAudios();
  if (!audios.length) return;
  if (currentTime >= duration - 0.05) currentTime = 0;

  for (const audio of audios) {
    audio.currentTime = currentTime;
    audio.play();
  }

  isPlaying = true;
  playToggle.classList.remove("is-paused");
  playToggle.classList.add("is-playing");
  playToggle.setAttribute("aria-label", "일시정지");
  updateAudioState();
  startTimer();
}

function pauseAll(resetState = true) {
  activeAudios().forEach((audio) => audio.pause());
  if (resetState) {
    isPlaying = false;
    playToggle.classList.remove("is-playing");
    playToggle.classList.add("is-paused");
    playToggle.setAttribute("aria-label", "재생");
    window.clearInterval(timer);
  }
}

function seekTo(value) {
  currentTime = Math.max(0, Math.min(duration, value));
  activeAudios().forEach((audio) => {
    audio.currentTime = currentTime;
  });
  currentTimeLabel.textContent = formatTime(currentTime);
  updatePlayhead();

  if (isPlaying) {
    playbackAudios().forEach((audio) => {
      if (audio.paused) audio.play();
    });
  }
}

function updateAudioState() {
  const playable = playbackAudios();
  for (const audio of activeAudios()) {
    const shouldPlay = playable.includes(audio);
    audio.muted = !shouldPlay;
    if (!shouldPlay) {
      audio.pause();
      continue;
    }
    if (isPlaying && audio.paused) {
      audio.currentTime = currentTime;
      audio.play();
    }
  }
}

function startTimer() {
  window.clearInterval(timer);
  timer = window.setInterval(() => {
    const first = playbackAudios()[0];
    if (!first) return;

    currentTime = first.currentTime || currentTime;
    if (currentTime >= duration - 0.04 || playbackAudios().every((audio) => audio.ended)) {
      currentTime = 0;
      pauseAll();
      activeAudios().forEach((audio) => {
        audio.currentTime = 0;
      });
    }

    currentTimeLabel.textContent = formatTime(currentTime);
    updatePlayhead();
  }, 80);
}

function updatePlayhead() {
  const head = document.querySelector("#global-playhead");
  const firstWave = document.querySelector(".track-row:not(.disabled) .wave-shell");
  const lastWave = [...document.querySelectorAll(".track-row:not(.disabled) .wave-shell")].at(-1);
  if (!head || !firstWave || !lastWave) return;

  const stackRect = trackStack.getBoundingClientRect();
  const firstRect = firstWave.getBoundingClientRect();
  const lastRect = lastWave.getBoundingClientRect();
  const ratio = duration ? currentTime / duration : 0;

  head.classList.remove("hidden");
  head.style.left = `${firstRect.left - stackRect.left + firstRect.width * ratio}px`;
  head.style.top = `${firstRect.top - stackRect.top}px`;
  head.style.height = `${lastRect.bottom - firstRect.top}px`;
}

function drawWaveform(canvas, peaks, active) {
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = active ? "#f6faf7" : "#eeeeee";
  ctx.fillRect(0, 0, width, height);
  if (!active) return;

  const values = Array.isArray(peaks) && peaks.length ? peaks : new Array(120).fill(0);
  const mid = height / 2;
  const barWidth = width / values.length;

  values.forEach((peak, index) => {
    const x = index * barWidth;
    const h = Math.max(2, peak * (height * 0.78));
    ctx.fillStyle = active ? "#31c06b" : "#d6d6d6";
    ctx.fillRect(x, mid - h / 2, Math.max(1, barWidth + 0.5), h);
  });
}

function collectMixState() {
  const tracks = [...document.querySelectorAll(".track-row")].map((row) => {
    const audio = row.querySelector("audio[data-stem]");
    const volume = row.querySelector(".vertical-volume");
    const value = Number(volume?.value ?? 0);
    return {
      name: row.dataset.stem,
      volume: value,
      muted: audio?.dataset.userMuted === "true" || value < VOLUME_MUTE_THRESHOLD,
      active: !row.classList.contains("disabled"),
    };
  });

  return { tracks, solo: soloStem };
}

function activeAudios() {
  return [...document.querySelectorAll(".track-row:not(.disabled) audio[data-stem]")];
}

function playbackAudios() {
  const audios = activeAudios();
  if (soloStem) {
    return audios.filter((audio) => audio.dataset.stem === soloStem);
  }
  return audios.filter((audio) => {
    const row = audio.closest(".track-row");
    const volume = Number(row?.querySelector(".vertical-volume")?.value ?? 0);
    return audio.dataset.userMuted !== "true" && volume >= VOLUME_MUTE_THRESHOLD;
  });
}

function selectedDevice() {
  return document.querySelector('input[name="device"]:checked')?.value ?? "auto";
}

function safeFileName(name) {
  return String(name)
    .replace(/\.[^/.]+$/, "")
    .replace(/[\\/:*?"<>|]+/g, "-")
    .replace(/\s+/g, " ")
    .trim() || "cyEbis";
}

function orderStems(stems) {
  const order = ["guitar", "bass", "drums", "vocals", "synth_other"];
  return [...stems].sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name));
}

function displayStemLabel(name) {
  return stemLabels[name] ?? name;
}

function readableStemName(name) {
  return stemDescriptions[name] ?? name;
}

function progressMessage(job) {
  if (job.status === "queued") return "처리 대기 중입니다.";
  if (job.status === "failed") return "분리에 실패했습니다.";
  if (job.progress < 0.2) return "오디오를 준비하는 중입니다.";
  if (job.progress < 0.75) return "Demucs로 stem을 분리하는 중입니다.";
  if (job.progress < 1) return "파형과 결과 파일을 준비하는 중입니다.";
  return "Stem 분리가 완료되었습니다.";
}

function formatTime(value) {
  const seconds = Math.max(0, Math.floor(value));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
