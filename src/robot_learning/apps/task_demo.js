const statusElement = document.getElementById("status");
let currentStatus = null;

function showStatus(value) {
  currentStatus = value.status || value;
  statusElement.textContent = JSON.stringify(value, null, 2);
}

async function send(path, payload) {
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    showStatus(response.ok ? data : {error: data.error, status: data.status || currentStatus});
  } catch (error) {
    showStatus({error: String(error), status: currentStatus});
  }
}

document.getElementById("propose").addEventListener("click", () => {
  send("/api/propose", {utterance: document.getElementById("utterance").value});
});
document.getElementById("approve").addEventListener("click", () => {
  send("/api/approve", {proposal_id: currentStatus && currentStatus.proposal_id});
});
document.getElementById("preview").addEventListener("click", () => send("/api/preview", {}));
document.getElementById("stop").addEventListener("click", () => send("/api/stop", {}));

fetch("/api/status").then(response => response.json()).then(showStatus).catch(error => {
  showStatus({error: String(error)});
});
