// Arduino App Lab draft integration for the S7-OPC UA Gateway API
// UI element IDs expected in App Lab Design mode:
// apiBaseInput, plcIpInput, plcPortInput, rackInput, slotInput, dbInput, opcuaPortInput,
// discoverBtn, variableDropdown, friendlyNameInput, addMapBtn, mappingsTextArea,
// saveConfigBtn, refreshStatusBtn, plcStatusLabel, opcuaStatusLabel, logLabel

var discovered = [];
var selectedMappings = {}; // key: original name -> mapping object

function apiBase() {
  return getText("apiBaseInput").trim().replace(/\/$/, "");
}

function log(msg) {
  setText("logLabel", msg);
}

function req(method, path, body, onOk, onErr) {
  var url = apiBase() + path;
  var payload = body ? JSON.stringify(body) : "";
  startWebRequest(url, method, payload, function(status, response, headers) {
    if (status >= 200 && status < 300) {
      try {
        onOk(response ? JSON.parse(response) : {});
      } catch (e) {
        onErr("Invalid JSON response");
      }
    } else {
      onErr("HTTP " + status + " -> " + response);
    }
  });
}

function currentPlc() {
  return {
    host: getText("plcIpInput"),
    port: Number(getText("plcPortInput") || "102"),
    rack: Number(getText("rackInput") || "0"),
    slot: Number(getText("slotInput") || "1"),
    db_number: Number(getText("dbInput") || "1")
  };
}

function refreshMappingsPreview() {
  var arr = [];
  for (var key in selectedMappings) {
    arr.push(selectedMappings[key]);
  }
  setText("mappingsTextArea", JSON.stringify(arr, null, 2));
}

onEvent("discoverBtn", "click", function() {
  log("Discovering...");
  req("POST", "/discover", currentPlc(), function(data) {
    discovered = data.variables || [];
    var names = [];
    for (var i = 0; i < discovered.length; i++) {
      names.push(discovered[i].name);
    }
    setProperty("variableDropdown", "options", names);
    if (names.length > 0) {
      setText("friendlyNameInput", names[0]);
    }
    log("Discovered " + names.length + " variables");
  }, function(err) {
    log("Discovery failed: " + err);
  });
});

onEvent("variableDropdown", "change", function() {
  var name = getText("variableDropdown");
  setText("friendlyNameInput", name);
});

onEvent("addMapBtn", "click", function() {
  var selected = getText("variableDropdown");
  var friendly = getText("friendlyNameInput").trim();
  if (!selected) {
    log("Select a variable first");
    return;
  }
  if (!friendly) {
    log("Enter a friendly name");
    return;
  }

  var item = null;
  for (var i = 0; i < discovered.length; i++) {
    if (discovered[i].name === selected) {
      item = discovered[i];
      break;
    }
  }
  if (!item) {
    log("Variable not found");
    return;
  }

  var layout = item.layout || {};
  selectedMappings[selected] = {
    name: selected,
    display_name: friendly,
    enabled: true,
    data_type: layout.data_type,
    byte_offset: layout.byte_offset,
    bit_offset: layout.bit_offset
  };

  refreshMappingsPreview();
  log("Mapped " + selected + " -> " + friendly);
});

onEvent("saveConfigBtn", "click", function() {
  var mappings = [];
  for (var k in selectedMappings) {
    mappings.push(selectedMappings[k]);
  }

  var cfg = {
    plc: currentPlc(),
    opcua_port: Number(getText("opcuaPortInput") || "4840"),
    variables: mappings
  };

  req("POST", "/save-config", cfg, function(data) {
    log("Config saved: " + (data.path || "ok"));
  }, function(err) {
    log("Save failed: " + err);
  });
});

function refreshStatus() {
  req("GET", "/status", null, function(data) {
    setText("plcStatusLabel", data.plc_connected ? "PLC: Connected" : "PLC: Disconnected");
    setText("opcuaStatusLabel", data.opcua_running ? "OPC UA: Running" : "OPC UA: Stopped");
  }, function(err) {
    setText("plcStatusLabel", "PLC: Unavailable");
    setText("opcuaStatusLabel", "OPC UA: Unavailable");
    log("Status error: " + err);
  });
}

onEvent("refreshStatusBtn", "click", refreshStatus);
timedLoop(5000, refreshStatus);
