const spectrumCanvas = document.getElementById("spectrum");
const waterfallCanvas = document.getElementById("waterfall");
const spectrumCtx = spectrumCanvas.getContext("2d");
const waterfallCtx = waterfallCanvas.getContext("2d");

const centerInput = document.getElementById("centerMhz");
const modeSelect = document.getElementById("modeSelect");
const sampleRateSelect = document.getElementById("sampleRate");
const autoGainInput = document.getElementById("autoGain");
const gainInput = document.getElementById("gainDb");
const pauseButton = document.getElementById("pauseButton");
const pauseGlyph = document.getElementById("pauseGlyph");
const listenButton = document.getElementById("listenButton");
const scanButton = document.getElementById("scanButton");
const runState = document.getElementById("runState");
const peakState = document.getElementById("peakState");
const deviceLine = document.getElementById("deviceLine");
const scopeMeta = document.getElementById("scopeMeta");
const waterfallMeta = document.getElementById("waterfallMeta");
const snrReadout = document.getElementById("snrReadout");
const peakList = document.getElementById("peakList");
const scanList = document.getElementById("scanList");
const presetTabs = document.getElementById("presetTabs");
const presetGrid = document.getElementById("presetGrid");
const scanGroup = document.getElementById("scanGroup");

let presets = [];
let activeGroup = "";
let running = true;
let spectrumBusy = false;
let audioRunning = false;
let audioBusy = false;
let audioContext = null;
let activeAudioController = null;
let audioSources = new Set();
let nextAudioStart = 0;
let smoothedBins = null;
let waterfallReady = false;
let pollDelay = 260;

function text(el, value) {
  if (el && el.textContent !== value) el.textContent = value;
}

function pill(el, value, quiet = false) {
  text(el, value);
  el.classList.toggle("quiet", quiet);
}

function formatMhz(hz) {
  return `${(Number(hz) / 1_000_000).toFixed(3)} MHz`;
}

function params() {
  const q = new URLSearchParams();
  q.set("center_mhz", centerInput.value || "162.55");
  q.set("sample_rate", sampleRateSelect.value || "1024000");
  q.set("auto_gain", autoGainInput.checked ? "1" : "0");
  q.set("fft_size", "2048");
  if (!autoGainInput.checked) q.set("gain_db", gainInput.value || "28");
  return q;
}

function audioParams() {
  const q = new URLSearchParams();
  q.set("center_mhz", centerInput.value || "162.55");
  q.set("mode", modeSelect.value || "nfm");
  q.set("seconds", "0.74");
  q.set("squelch", "1");
  q.set("auto_gain", autoGainInput.checked ? "1" : "0");
  if (!autoGainInput.checked) q.set("gain_db", gainInput.value || "28");
  return q;
}

async function apiJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  const payload = await res.json();
  if (!res.ok || payload.ok === false) {
    throw new Error(payload.error || `HTTP ${res.status}`);
  }
  return payload;
}

function drawSpectrum(payload) {
  const bins = payload.bins || [];
  if (!bins.length) return;
  if (!smoothedBins || smoothedBins.length !== bins.length) {
    smoothedBins = bins.slice();
  } else {
    for (let i = 0; i < bins.length; i += 1) {
      smoothedBins[i] = smoothedBins[i] * 0.72 + bins[i] * 0.28;
    }
  }

  const w = spectrumCanvas.width;
  const h = spectrumCanvas.height;
  spectrumCtx.clearRect(0, 0, w, h);
  spectrumCtx.fillStyle = "#07090a";
  spectrumCtx.fillRect(0, 0, w, h);
  spectrumCtx.strokeStyle = "rgba(124, 183, 255, 0.16)";
  spectrumCtx.lineWidth = 1;
  for (let i = 1; i < 6; i += 1) {
    const y = (h / 6) * i;
    spectrumCtx.beginPath();
    spectrumCtx.moveTo(0, y);
    spectrumCtx.lineTo(w, y);
    spectrumCtx.stroke();
  }

  const min = Math.min(...smoothedBins);
  const max = Math.max(...smoothedBins);
  const span = Math.max(8, max - min);
  spectrumCtx.beginPath();
  for (let i = 0; i < smoothedBins.length; i += 1) {
    const x = (i / Math.max(1, smoothedBins.length - 1)) * w;
    const y = h - ((smoothedBins[i] - min) / span) * (h - 18) - 9;
    if (i === 0) spectrumCtx.moveTo(x, y);
    else spectrumCtx.lineTo(x, y);
  }
  spectrumCtx.strokeStyle = "#42e8d2";
  spectrumCtx.lineWidth = 2;
  spectrumCtx.stroke();

  const peakBin = Math.max(0, Math.min(smoothedBins.length - 1, Math.round((payload.peak_hz - payload.freq_start_hz) / payload.freq_step_hz / (payload.fft_size / smoothedBins.length))));
  const peakX = (peakBin / Math.max(1, smoothedBins.length - 1)) * w;
  spectrumCtx.strokeStyle = "rgba(244, 198, 91, 0.9)";
  spectrumCtx.beginPath();
  spectrumCtx.moveTo(peakX, 0);
  spectrumCtx.lineTo(peakX, h);
  spectrumCtx.stroke();
}

function drawWaterfall(payload) {
  const bins = payload.bins || [];
  if (!bins.length) return;
  const w = waterfallCanvas.width;
  const h = waterfallCanvas.height;
  if (!waterfallReady) {
    waterfallCtx.fillStyle = "#07090a";
    waterfallCtx.fillRect(0, 0, w, h);
    waterfallReady = true;
  }
  waterfallCtx.drawImage(waterfallCanvas, 0, 0, w, h - 1, 0, 1, w, h - 1);
  const min = Math.min(...bins);
  const max = Math.max(...bins);
  const span = Math.max(8, max - min);
  const image = waterfallCtx.createImageData(w, 1);
  for (let x = 0; x < w; x += 1) {
    const idx = Math.floor((x / w) * bins.length);
    const v = Math.max(0, Math.min(1, (bins[idx] - min) / span));
    const offset = x * 4;
    image.data[offset] = Math.round(18 + 230 * Math.max(0, v - 0.35));
    image.data[offset + 1] = Math.round(45 + 190 * v);
    image.data[offset + 2] = Math.round(58 + 150 * (1 - Math.abs(v - 0.65)));
    image.data[offset + 3] = 255;
  }
  waterfallCtx.putImageData(image, 0, 0);
}

function updateSignalList(list, items, tunable = true) {
  const normalized = items.length ? items : [{ mhz: "--", snr: 0, label: "No signal", hz: 0 }];
  list.replaceChildren(
    ...normalized.slice(0, 8).map((item) => {
      const li = document.createElement("li");
      if (tunable && item.hz) li.classList.add("tunable");
      const freq = document.createElement("span");
      freq.className = "freq";
      freq.textContent = item.hz ? (item.hz / 1_000_000).toFixed(3) : "--";
      const bar = document.createElement("span");
      bar.className = "bar";
      const snr = Number(item.snr ?? item.snr_db ?? 0);
      bar.style.transform = `scaleX(${Math.max(0.05, Math.min(1, snr / 32)).toFixed(3)})`;
      const strength = document.createElement("span");
      strength.className = "strength";
      strength.textContent = item.hz ? `${snr.toFixed(1)} dB` : "";
      li.title = item.name || item.group || "";
      li.append(freq, bar, strength);
      if (item.hz) {
        li.addEventListener("click", () => {
          tune(item.mhz || item.hz / 1_000_000, item.mode || modeSelect.value);
        });
      }
      return li;
    })
  );
}

function renderPresets() {
  presetTabs.replaceChildren();
  scanGroup.replaceChildren();
  presets.forEach((group) => {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "tab-button";
    tab.textContent = group.name;
    tab.classList.toggle("active", group.id === activeGroup);
    tab.addEventListener("click", () => {
      activeGroup = group.id;
      renderPresets();
    });
    presetTabs.append(tab);

    const opt = document.createElement("option");
    opt.value = group.id;
    opt.textContent = group.name;
    scanGroup.append(opt);
  });
  scanGroup.value = activeGroup || presets[0]?.id || "";

  const active = presets.find((group) => group.id === activeGroup) || presets[0];
  presetGrid.replaceChildren();
  if (!active) return;
  active.channels.forEach((channel) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "preset-button";
    button.innerHTML = `<strong></strong><span></span>`;
    button.querySelector("strong").textContent = channel.name;
    button.querySelector("span").textContent = `${Number(channel.mhz).toFixed(4)} MHz`;
    button.addEventListener("click", () => tune(channel.mhz, active.mode));
    presetGrid.append(button);
  });
}

function tune(mhz, mode) {
  centerInput.value = Number(mhz).toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  modeSelect.value = mode || modeSelect.value;
  smoothedBins = null;
  waterfallReady = false;
  if (audioRunning) {
    stopAudio(false);
    startAudio();
  }
  tick();
}

async function loadPresets() {
  const payload = await apiJson("api/presets");
  presets = payload.groups || [];
  activeGroup = presets[0]?.id || "";
  renderPresets();
}

async function refreshStatus() {
  try {
    const payload = await apiJson("api/status");
    if (payload.radio_available) {
      text(deviceLine, payload.device?.name || "RTL-SDR connected");
      pill(runState, running ? "Live" : "Paused");
    } else {
      text(deviceLine, payload.error || "Receiver unavailable");
      pill(runState, "Driver needed", true);
    }
  } catch (error) {
    text(deviceLine, error.message);
    pill(runState, "Offline", true);
  }
}

async function tick() {
  if (!running || spectrumBusy || document.hidden) return;
  spectrumBusy = true;
  try {
    const payload = await apiJson(`api/spectrum?${params().toString()}`);
    drawSpectrum(payload);
    drawWaterfall(payload);
    text(scopeMeta, `${formatMhz(payload.center_hz)} center | ${(payload.sample_rate / 1_000_000).toFixed(3)} MS/s`);
    text(waterfallMeta, `${payload.bins.length} bins`);
    text(snrReadout, `${Number(payload.snr_db).toFixed(1)} dB`);
    pill(peakState, `Peak ${formatMhz(payload.peak_hz)}`);
    if (!audioRunning) pill(runState, "Live");
    updateSignalList(peakList, payload.peaks || []);
    pollDelay = 260;
  } catch (error) {
    pill(runState, "Waiting", true);
    text(scopeMeta, error.message);
    pollDelay = 900;
  } finally {
    spectrumBusy = false;
    window.setTimeout(tick, pollDelay);
  }
}

async function scan() {
  scanButton.disabled = true;
  pill(runState, "Scanning");
  try {
    const payload = await apiJson(`api/scan?group=${encodeURIComponent(scanGroup.value || activeGroup || "weather")}`);
    updateSignalList(scanList, payload.results || [], true);
    pill(runState, "Scan done");
  } catch (error) {
    updateSignalList(scanList, []);
    pill(runState, "Scan failed", true);
  } finally {
    scanButton.disabled = false;
  }
}

function stopAudio(update = true) {
  audioRunning = false;
  audioBusy = false;
  if (activeAudioController) activeAudioController.abort();
  activeAudioController = null;
  for (const source of audioSources) {
    try {
      source.stop();
    } catch (error) {}
  }
  audioSources.clear();
  nextAudioStart = 0;
  if (update) {
    text(listenButton, "Listen Live");
    pill(runState, running ? "Live" : "Paused", !running);
  }
}

async function startAudio() {
  if (audioRunning) {
    stopAudio();
    return;
  }
  audioRunning = true;
  text(listenButton, "Stop Audio");
  pill(runState, "Listening");
  audioLoop();
}

async function audioLoop() {
  if (!audioRunning || audioBusy) return;
  audioBusy = true;
  try {
    if (!audioContext) audioContext = new AudioContext();
    await audioContext.resume();
    activeAudioController = new AbortController();
    const res = await fetch(`api/audio?${audioParams().toString()}`, {
      cache: "no-store",
      signal: activeAudioController.signal,
    });
    if (!res.ok) throw new Error(`audio ${res.status}`);
    const audioData = await res.arrayBuffer();
    if (!audioRunning) return;
    const decoded = await audioContext.decodeAudioData(audioData);
    if (!audioRunning) return;
    const source = audioContext.createBufferSource();
    source.buffer = decoded;
    source.connect(audioContext.destination);
    source.onended = () => audioSources.delete(source);
    audioSources.add(source);
    nextAudioStart = Math.max(audioContext.currentTime + 0.025, nextAudioStart || 0);
    source.start(nextAudioStart);
    nextAudioStart += decoded.duration;
    pill(runState, "Listening");
  } catch (error) {
    if (audioRunning && error.name !== "AbortError") {
      pill(runState, "Audio wait", true);
    }
  } finally {
    audioBusy = false;
    if (audioRunning) window.setTimeout(audioLoop, 80);
  }
}

autoGainInput.addEventListener("change", () => {
  gainInput.disabled = autoGainInput.checked;
});

pauseButton.addEventListener("click", () => {
  running = !running;
  text(pauseGlyph, running ? "Pause" : "Run");
  pill(runState, running ? "Live" : "Paused", !running);
  if (running) tick();
});

listenButton.addEventListener("click", startAudio);
scanButton.addEventListener("click", scan);
scanGroup.addEventListener("change", () => {
  activeGroup = scanGroup.value;
  renderPresets();
});

[centerInput, modeSelect, sampleRateSelect, gainInput].forEach((element) => {
  element.addEventListener("change", () => {
    smoothedBins = null;
    waterfallReady = false;
    if (running) tick();
  });
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && running) tick();
});

(async function boot() {
  drawSpectrum({ bins: new Array(512).fill(0), peak_hz: 0, freq_start_hz: 0, freq_step_hz: 1, fft_size: 2048 });
  await Promise.allSettled([loadPresets(), refreshStatus()]);
  tick();
})();
