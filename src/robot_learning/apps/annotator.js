const episodeSelect = document.querySelector("#episode");
const annotatorInput = document.querySelector("#annotator");
const spansTable = document.querySelector("#spans");
const statusLine = document.querySelector("#status");
const summaryLine = document.querySelector("#summary");

async function request(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function field(type, value) {
  const input = document.createElement("input");
  input.type = type;
  if (type === "number") {
    input.min = "0";
    input.step = "1";
  }
  if (type === "checkbox") input.checked = Boolean(value);
  else input.value = String(value);
  return input;
}

function addSpan(span = {start_index: 0, end_index: 1, text: "", used_for_vlm: false}) {
  const row = document.createElement("tr");
  const fields = [
    field("number", span.start_index),
    field("number", span.end_index),
    field("text", span.text),
    field("checkbox", span.used_for_vlm),
  ];
  for (const input of fields) {
    const cell = document.createElement("td");
    cell.append(input);
    row.append(cell);
  }
  const removeCell = document.createElement("td");
  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.textContent = "删除";
  removeButton.addEventListener("click", () => row.remove());
  removeCell.append(removeButton);
  row.append(removeCell);
  spansTable.append(row);
}

async function loadEpisode() {
  spansTable.replaceChildren();
  if (!episodeSelect.value) return;
  try {
    const episode = await request(`/api/episodes/${encodeURIComponent(episodeSelect.value)}`);
    summaryLine.textContent = `${episode.name} · ${episode.frame_count} 帧 · ${episode.metadata.robot_model}`;
    annotatorInput.value = episode.annotation?.annotator || "";
    for (const span of episode.annotation?.spans || []) addSpan(span);
    statusLine.textContent = "";
  } catch (error) {
    statusLine.textContent = error.message;
  }
}

async function saveAnnotation() {
  if (!episodeSelect.value) return;
  const spans = Array.from(spansTable.querySelectorAll("tr"), row => {
    const fields = row.querySelectorAll("input");
    return {
      start_index: Number(fields[0].value),
      end_index: Number(fields[1].value),
      text: fields[2].value,
      used_for_vlm: fields[3].checked,
    };
  });
  try {
    await request(`/api/episodes/${encodeURIComponent(episodeSelect.value)}/annotation`, {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({annotator: annotatorInput.value, spans}),
    });
    statusLine.textContent = "保存成功";
  } catch (error) {
    statusLine.textContent = error.message;
  }
}

episodeSelect.addEventListener("change", loadEpisode);
document.querySelector("#add-span").addEventListener("click", () => addSpan());
document.querySelector("#save").addEventListener("click", saveAnnotation);

request("/api/episodes").then(data => {
  for (const name of data.episodes) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    episodeSelect.append(option);
  }
  if (data.episodes.length) loadEpisode();
  else statusLine.textContent = "数据目录中尚无 Episode";
}).catch(error => { statusLine.textContent = error.message; });
