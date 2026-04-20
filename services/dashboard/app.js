const state = {
  discoveredVariables: [],
  statusTimer: null,
};

const elements = {
  apiBaseUrl: document.getElementById("apiBaseUrl"),
  saveApiBase: document.getElementById("saveApiBase"),
  plcHost: document.getElementById("plcHost"),
  plcRack: document.getElementById("plcRack"),
  plcSlot: document.getElementById("plcSlot"),
  plcPort: document.getElementById("plcPort"),
  dbNumber: document.getElementById("dbNumber"),
  opcuaPort: document.getElementById("opcuaPort"),
  discoverBtn: document.getElementById("discoverBtn"),
  refreshStatusBtn: document.getElementById("refreshStatusBtn"),
  saveConfigBtn: document.getElementById("saveConfigBtn"),
  plcStatus: document.getElementById("plcStatus"),
  opcuaStatus: document.getElementById("opcuaStatus"),
  lastStatus: document.getElementById("lastStatus"),
  messageBar: document.getElementById("messageBar"),
  variablesBody: document.getElementById("variablesBody"),
  variableRowTemplate: document.getElementById("variableRowTemplate"),
};

const DEFAULT_API_BASE = "http://localhost:8080";
const API_BASE_STORAGE_KEY = "gatewayApiBaseUrl";
const PLC_SETTINGS_STORAGE_KEY = "gatewayPlcSettings";

function loadStoredJson(key) {
  try {
    return JSON.parse(localStorage.getItem(key) || "null");
  } catch {
    return null;
  }
}

function saveStoredJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function getApiBaseUrl() {
  return (elements.apiBaseUrl.value || DEFAULT_API_BASE).trim().replace(/\/$/, "");
}

function setMessage(text, kind = "info") {
  elements.messageBar.hidden = !text;
  elements.messageBar.textContent = text;
  elements.messageBar.className = `message ${kind}`;
}

function setStatusBadge(element, value, kind) {
  element.textContent = value;
  element.classList.remove("pill-good", "pill-warn", "pill-bad");
  element.classList.add(kind);
}

function formatNumber(value) {
  return value === null || value === undefined || value === "" ? "—" : value;
}

function createVariableRow(variable) {
  const row = elements.variableRowTemplate.content.firstElementChild.cloneNode(true);
  const enabledInput = row.querySelector(".row-enabled");
  const displayInput = row.querySelector(".row-display-name");

  enabledInput.checked = variable.enabled !== false;
  row.querySelector(".tag-name").textContent = variable.name;
  row.querySelector(".row-type").textContent = variable.data_type || variable.layout?.data_type || "—";
  row.querySelector(".row-db").textContent = variable.db_number ?? "—";
  row.querySelector(".row-byte").textContent = formatNumber(variable.byte_offset ?? variable.layout?.byte_offset);
  row.querySelector(".row-bit").textContent = formatNumber(variable.bit_offset ?? variable.layout?.bit_offset);
  displayInput.value = variable.display_name || variable.name;
  displayInput.placeholder = variable.name;

  row.dataset.variableName = variable.name;
  row.dataset.layout = JSON.stringify(variable.layout || {});

  return row;
}

function getCurrentVariables() {
  return Array.from(elements.variablesBody.querySelectorAll("tr[data-variable-name]")).map((row) => {
    const layout = JSON.parse(row.dataset.layout || "{}");
    const enabled = row.querySelector(".row-enabled").checked;
    const displayName = row.querySelector(".row-display-name").value.trim() || row.dataset.variableName;

    return {
      name: row.dataset.variableName,
      display_name: displayName,
      enabled,
      ...layout,
    };
  });
}

async function requestJson(path, options = {}) {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = payload.error || payload.detail || response.statusText;
    throw new Error(error);
  }
  return payload;
}

async function discoverVariables() {
  setMessage("Discovering PLC variables...", "info");
  elements.discoverBtn.disabled = true;

  try {
    const payload = await requestJson("/discover", {
      method: "POST",
      body: JSON.stringify({
        host: elements.plcHost.value.trim(),
        rack: Number(elements.plcRack.value || 0),
        slot: Number(elements.plcSlot.value || 1),
        port: Number(elements.plcPort.value || 102),
        db_number: Number(elements.dbNumber.value || 1),
      }),
    });

    elements.variablesBody.innerHTML = "";
    state.discoveredVariables = payload.variables || [];

    saveStoredJson(PLC_SETTINGS_STORAGE_KEY, {
      plc: {
        host: elements.plcHost.value.trim(),
        rack: Number(elements.plcRack.value || 0),
        slot: Number(elements.plcSlot.value || 1),
        port: Number(elements.plcPort.value || 102),
        db_number: Number(elements.dbNumber.value || 1),
      },
      opcua_port: Number(elements.opcuaPort.value || 4840),
    });

    if (!state.discoveredVariables.length) {
      elements.variablesBody.innerHTML = '<tr class="empty-row"><td colspan="7">No variables returned.</td></tr>';
    } else {
      for (const variable of state.discoveredVariables) {
        elements.variablesBody.appendChild(createVariableRow(variable));
      }
    }

    setMessage(`Discovered ${state.discoveredVariables.length} variables from the PLC.`, "success");
  } catch (error) {
    setMessage(`Discovery failed: ${error.message}`, "error");
  } finally {
    elements.discoverBtn.disabled = false;
  }
}

async function saveConfig() {
  setMessage("Saving gateway config...", "info");
  elements.saveConfigBtn.disabled = true;

  try {
    const config = {
      plc: {
        host: elements.plcHost.value.trim(),
        rack: Number(elements.plcRack.value || 0),
        slot: Number(elements.plcSlot.value || 1),
        port: Number(elements.plcPort.value || 102),
        db_number: Number(elements.dbNumber.value || 1),
      },
      opcua_port: Number(elements.opcuaPort.value || 4840),
      variables: getCurrentVariables(),
    };

    const payload = await requestJson("/save-config", {
      method: "POST",
      body: JSON.stringify(config),
    });

    saveStoredJson(PLC_SETTINGS_STORAGE_KEY, config);
    setMessage(`Config saved to ${payload.path}`, "success");
  } catch (error) {
    setMessage(`Save failed: ${error.message}`, "error");
  } finally {
    elements.saveConfigBtn.disabled = false;
  }
}

async function refreshStatus() {
  try {
    const payload = await requestJson("/status", { method: "GET" });
    setStatusBadge(elements.plcStatus, payload.plc_connected ? "Connected" : "Disconnected", payload.plc_connected ? "pill-good" : "pill-bad");
    setStatusBadge(elements.opcuaStatus, payload.opcua_running ? "Running" : "Stopped", payload.opcua_running ? "pill-good" : "pill-bad");
    elements.lastStatus.textContent = payload.last_error || new Date().toLocaleTimeString();
  } catch (error) {
    setStatusBadge(elements.plcStatus, "Unavailable", "pill-warn");
    setStatusBadge(elements.opcuaStatus, "Unavailable", "pill-warn");
    elements.lastStatus.textContent = error.message;
  }
}

function loadStoredState() {
  elements.apiBaseUrl.value = localStorage.getItem(API_BASE_STORAGE_KEY) || DEFAULT_API_BASE;

  const saved = loadStoredJson(PLC_SETTINGS_STORAGE_KEY);
  if (saved?.plc) {
    elements.plcHost.value = saved.plc.host ?? "";
    elements.plcRack.value = saved.plc.rack ?? 0;
    elements.plcSlot.value = saved.plc.slot ?? 1;
    elements.plcPort.value = saved.plc.port ?? 102;
    elements.dbNumber.value = saved.plc.db_number ?? 1;
  }

  if (saved?.opcua_port) {
    elements.opcuaPort.value = saved.opcua_port;
  }
}

function bindEvents() {
  elements.saveApiBase.addEventListener("click", () => {
    localStorage.setItem(API_BASE_STORAGE_KEY, getApiBaseUrl());
    setMessage("API base URL saved locally.", "success");
  });

  elements.discoverBtn.addEventListener("click", discoverVariables);
  elements.refreshStatusBtn.addEventListener("click", refreshStatus);
  elements.saveConfigBtn.addEventListener("click", saveConfig);
}

function startStatusPolling() {
  refreshStatus();
  state.statusTimer = window.setInterval(refreshStatus, 5000);
}

loadStoredState();
bindEvents();
startStatusPolling();
