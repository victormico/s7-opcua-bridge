// Dashboard for the S7 -> OPC UA Gateway App Lab app.
//
// Transport is the arduino:web_ui Brick's Socket.IO channel (window.WebUI from
// libs/arduino.js), not HTTP. The DOM/rendering logic mirrors the original
// standalone dashboard; only the request layer changed.

const state = {
  simRunning: false,
};

const elements = {
  plcHost: document.getElementById("plcHost"),
  plcRack: document.getElementById("plcRack"),
  plcSlot: document.getElementById("plcSlot"),
  plcPort: document.getElementById("plcPort"),
  dbNumber: document.getElementById("dbNumber"),
  opcuaPort: document.getElementById("opcuaPort"),
  discoverBtn: document.getElementById("discoverBtn"),
  refreshStatusBtn: document.getElementById("refreshStatusBtn"),
  saveConfigBtn: document.getElementById("saveConfigBtn"),
  simToggleBtn: document.getElementById("simToggleBtn"),
  plcStatus: document.getElementById("plcStatus"),
  opcuaStatus: document.getElementById("opcuaStatus"),
  lastStatus: document.getElementById("lastStatus"),
  messageBar: document.getElementById("messageBar"),
  variablesBody: document.getElementById("variablesBody"),
  variableRowTemplate: document.getElementById("variableRowTemplate"),
};

// --- UI helpers -------------------------------------------------------------

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

// Normalize either a discover result ({layout: {...}}) or a saved config
// variable ({byte_offset, data_type, bit_offset}) to a flat layout object.
function normalizeLayout(variable) {
  if (variable.layout) {
    return variable.layout;
  }
  const layout = {};
  if (variable.byte_offset !== undefined) layout.byte_offset = variable.byte_offset;
  if (variable.data_type !== undefined) layout.data_type = variable.data_type;
  if (variable.bit_offset !== undefined) layout.bit_offset = variable.bit_offset;
  return layout;
}

function createVariableRow(variable, dbFallback) {
  const row = elements.variableRowTemplate.content.firstElementChild.cloneNode(true);
  const layout = normalizeLayout(variable);
  const configured = variable.configured || null;

  const enabled =
    variable.enabled !== undefined
      ? variable.enabled !== false
      : configured
      ? configured.enabled !== false
      : true;
  const displayName =
    variable.display_name || (configured && configured.display_name) || variable.name;

  row.querySelector(".row-enabled").checked = enabled;
  row.querySelector(".tag-name").textContent = variable.name;
  row.querySelector(".row-type").textContent = layout.data_type || "—";
  row.querySelector(".row-db").textContent = formatNumber(variable.db_number ?? dbFallback);
  row.querySelector(".row-byte").textContent = formatNumber(layout.byte_offset);
  row.querySelector(".row-bit").textContent = formatNumber(layout.bit_offset);

  const displayInput = row.querySelector(".row-display-name");
  displayInput.value = displayName;
  displayInput.placeholder = variable.name;

  row.dataset.variableName = variable.name;
  row.dataset.layout = JSON.stringify(layout);
  return row;
}

function renderVariables(list, dbFallback) {
  elements.variablesBody.innerHTML = "";
  if (!list || !list.length) {
    elements.variablesBody.innerHTML =
      '<tr class="empty-row"><td colspan="7">No variables returned.</td></tr>';
    return;
  }
  for (const variable of list) {
    elements.variablesBody.appendChild(createVariableRow(variable, dbFallback));
  }
}

function getCurrentVariables() {
  return Array.from(elements.variablesBody.querySelectorAll("tr[data-variable-name]")).map(
    (row) => {
      const layout = JSON.parse(row.dataset.layout || "{}");
      return {
        name: row.dataset.variableName,
        display_name:
          row.querySelector(".row-display-name").value.trim() || row.dataset.variableName,
        enabled: row.querySelector(".row-enabled").checked,
        ...layout,
      };
    }
  );
}

function plcParams() {
  return {
    host: elements.plcHost.value.trim(),
    rack: Number(elements.plcRack.value || 0),
    slot: Number(elements.plcSlot.value || 1),
    port: Number(elements.plcPort.value || 1102),
    db_number: Number(elements.dbNumber.value || 1),
  };
}

function buildConfig() {
  return {
    plc: plcParams(),
    opcua_port: Number(elements.opcuaPort.value || 4840),
    variables: getCurrentVariables(),
  };
}

function updateSimButton() {
  elements.simToggleBtn.textContent = `Simulator: ${state.simRunning ? "ON" : "OFF"}`;
}

// --- WebUI wiring -----------------------------------------------------------

const ui = new WebUI();

ui.on_connect(() => {
  setMessage("");
  ui.send_message("get_initial_state");
});

ui.on_disconnect(() => {
  setMessage("Connection to the board lost. Reconnecting…", "error");
  setStatusBadge(elements.plcStatus, "Unavailable", "pill-warn");
  setStatusBadge(elements.opcuaStatus, "Unavailable", "pill-warn");
});

ui.on_message("initial_state", (data) => {
  const config = (data && data.config) || {};
  if (config.plc) {
    elements.plcHost.value = config.plc.host ?? elements.plcHost.value;
    elements.plcRack.value = config.plc.rack ?? 0;
    elements.plcSlot.value = config.plc.slot ?? 1;
    elements.plcPort.value = config.plc.port ?? 1102;
    elements.dbNumber.value = config.plc.db_number ?? 1;
  }
  if (config.opcua_port) {
    elements.opcuaPort.value = config.opcua_port;
  }
  if (config.variables && config.variables.length) {
    renderVariables(config.variables, config.plc && config.plc.db_number);
  }
  if (data && data.status) {
    applyStatus(data.status);
  }
});

ui.on_message("discover_result", (data) => {
  if (!data || data.error) {
    setMessage(`Discovery failed: ${(data && data.error) || "unknown error"}`, "error");
    return;
  }
  renderVariables(data.variables, data.plc && data.plc.db_number);
  setMessage(`Discovered ${data.variables.length} variables from the PLC.`, "success");
});

ui.on_message("save_result", (data) => {
  if (data && data.ok) {
    setMessage(`Config saved to ${data.path}. Reloading OPC UA nodes…`, "success");
  } else {
    setMessage(`Save failed: ${(data && data.error) || "unknown error"}`, "error");
  }
});

ui.on_message("status_update", applyStatus);

function applyStatus(status) {
  if (!status) return;
  setStatusBadge(
    elements.plcStatus,
    status.plc_connected ? "Connected" : "Disconnected",
    status.plc_connected ? "pill-good" : "pill-bad"
  );
  setStatusBadge(
    elements.opcuaStatus,
    status.opcua_running ? "Running" : "Stopped",
    status.opcua_running ? "pill-good" : "pill-bad"
  );
  elements.lastStatus.textContent =
    status.last_error || new Date().toLocaleTimeString();
  state.simRunning = Boolean(status.simulator_running);
  updateSimButton();
}

// --- Events -----------------------------------------------------------------

elements.discoverBtn.addEventListener("click", () => {
  setMessage("Discovering PLC variables…", "info");
  ui.send_message("discover", plcParams());
});

elements.saveConfigBtn.addEventListener("click", () => {
  setMessage("Saving gateway config…", "info");
  ui.send_message("save_config", buildConfig());
});

elements.refreshStatusBtn.addEventListener("click", () => {
  ui.send_message("get_status");
});

elements.simToggleBtn.addEventListener("click", () => {
  ui.send_message(state.simRunning ? "sim_stop" : "sim_start");
});

updateSimButton();
