const message = document.getElementById("message");
const captureStatus = document.getElementById("capture-status");
const taskStatus = document.getElementById("task-status");
const profileSelect = document.getElementById("profile");
const sessionSelect = document.getElementById("session");
let taskSnapshot = null;
let mediaRecorder = null;
let audioChunks = [];

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = response.headers.get("Content-Type")?.includes("application/json")
    ? await response.json() : {};
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function postJson(path, value = {}) {
  return request(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(value),
  });
}

function showMessage(text) {
  message.textContent = text;
}

function renderEpisodes(episodes) {
  const root = document.getElementById("episodes");
  root.replaceChildren();
  if (!episodes.length) {
    root.textContent = "当前数据目录没有 Episode";
    return;
  }
  for (const episode of episodes) {
    const row = document.createElement("div");
    row.className = "episode";
    const summary = document.createElement("span");
    summary.textContent = `${episode.name} · ${episode.valid ? "校验通过" : "校验失败"} · ${episode.frame_count} 帧 · ${episode.annotation_count} 条标注`;
    const link = document.createElement("a");
    link.href = `/annotate?episode=${encodeURIComponent(episode.name)}`;
    link.textContent = "标注";
    row.append(summary, link);
    root.append(row);
  }
}

function renderCaptureStatus(value) {
  captureStatus.textContent = JSON.stringify(value, null, 2);
  profileSelect.replaceChildren();
  for (const profile of value.profiles || []) {
    const option = document.createElement("option");
    option.value = profile.profile_id;
    option.textContent = `${profile.profile_id} (${profile.robot})`;
    profileSelect.append(option);
  }
  document.getElementById("capture-start").disabled = !(value.profiles || []).length;
  sessionSelect.replaceChildren();
  for (const session of (value.sessions || []).filter(item => item.state === "running")) {
    const option = document.createElement("option");
    option.value = session.session_id;
    option.textContent = `${session.profile_id} · ${session.session_id.slice(0, 8)}`;
    sessionSelect.append(option);
  }
  document.getElementById("capture-stop").disabled = !sessionSelect.options.length;
}

function renderTaskStatus(value) {
  taskSnapshot = value;
  taskStatus.textContent = JSON.stringify(value, null, 2);
  const enabled = Boolean(value.available_tasks);
  for (const id of ["propose", "record", "approve", "preview", "task-stop"]) {
    document.getElementById(id).disabled = !enabled;
  }
  if (enabled) {
    document.getElementById("approve").disabled = value.phase !== "awaiting_approval";
    document.getElementById("preview").disabled = value.phase !== "approved";
    document.getElementById("task-stop").disabled = value.phase === "stopped";
  }
}

async function refresh() {
  try {
    const [status, catalog] = await Promise.all([request("/api/status"), request("/api/catalog")]);
    renderCaptureStatus(status.captures);
    renderTaskStatus(status.tasks);
    renderEpisodes(catalog.episodes);
    showMessage(catalog.truncated ? "仅显示前 200 个 Episode。" : "状态已更新");
  } catch (error) {
    showMessage(error.message);
  }
}

document.getElementById("refresh").addEventListener("click", refresh);
document.getElementById("capture-start").addEventListener("click", async () => {
  try { await postJson("/api/captures/start", {profile_id: profileSelect.value}); await refresh(); }
  catch (error) { showMessage(error.message); }
});
document.getElementById("capture-stop").addEventListener("click", async () => {
  try { await postJson("/api/captures/stop", {session_id: sessionSelect.value}); await refresh(); }
  catch (error) { showMessage(error.message); }
});
document.getElementById("propose").addEventListener("click", async () => {
  try { renderTaskStatus(await postJson("/api/tasks/propose", {utterance: document.getElementById("utterance").value})); }
  catch (error) { showMessage(error.message); }
});
document.getElementById("approve").addEventListener("click", async () => {
  try { renderTaskStatus(await postJson("/api/tasks/approve", {proposal_id: taskSnapshot.proposal_id})); }
  catch (error) { showMessage(error.message); }
});
document.getElementById("preview").addEventListener("click", async () => {
  try { renderTaskStatus(await postJson("/api/tasks/preview")); }
  catch (error) { showMessage(error.message); }
});
document.getElementById("task-stop").addEventListener("click", async () => {
  try { renderTaskStatus(await postJson("/api/tasks/stop")); }
  catch (error) { showMessage(error.message); }
});

document.getElementById("record").addEventListener("click", async event => {
  const button = event.currentTarget;
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    button.textContent = "录音提议";
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];
    mediaRecorder.addEventListener("dataavailable", item => { if (item.data.size) audioChunks.push(item.data); });
    mediaRecorder.addEventListener("stop", async () => {
      stream.getTracks().forEach(track => track.stop());
      const audio = new Blob(audioChunks, {type: mediaRecorder.mimeType || "audio/webm"});
      try {
        const response = await fetch("/api/tasks/audio", {method: "POST", headers: {"Content-Type": audio.type}, body: audio});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        renderTaskStatus(data);
      } catch (error) { showMessage(error.message); }
    }, {once: true});
    mediaRecorder.start();
    button.textContent = "停止录音并提交";
    showMessage("正在录音；再次点击后提交到已配置语音服务。");
  } catch (error) {
    showMessage(`无法访问麦克风：${error.message}`);
  }
});

refresh();
