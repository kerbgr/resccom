// ResCCOM 2.1-d — Island Console frontend. Plain ES5-ish JS, no build
// step, no bundler: must run on a five-year-old Android browser (same
// bar as stack/services/config/portal/server.py's page).
"use strict";

var island = null;
var map = null;
var markers = [];
var selectedSiteIndex = null;

// -- operator token (2.1-f) ----------------------------------------------
// Required on every write endpoint (POST); read-only map/status needs
// none. Kept only in this browser's localStorage -- never sent anywhere
// but this origin, never written back into island.yaml.

function getOperatorToken() {
  try {
    return window.localStorage.getItem("operatorToken") || "";
  } catch (e) {
    return "";
  }
}

function setOperatorToken(token) {
  try {
    window.localStorage.setItem("operatorToken", token);
  } catch (e) {
    // ignore -- private browsing / storage disabled just means re-typing it
  }
}

function authedPost(url, body) {
  return fetch(url, {
    method: "POST",
    headers: { Authorization: "Bearer " + getOperatorToken() },
    body: body,
  });
}

function numOrNull(el) {
  var v = el.value;
  if (v === "" || v === null) return null;
  var n = Number(v);
  return isNaN(n) ? null : n;
}

function textOrNull(el) {
  var v = el.value.trim();
  return v === "" ? null : v;
}

// -- rendering the form from `island` -------------------------------------

// Every plain-text/number input is wired to write straight into `island`
// on every keystroke (wireStaticInputs, wireSiteInputs) rather than being
// read once when Preview/Apply is clicked -- a later re-render (e.g.
// "add cell", which re-renders the whole site form to show the new
// card) would otherwise stomp an unsaved edit back to its last-rendered
// value. `island` is always the single source of truth; render*()
// functions only ever *display* it.

function renderIdentity() {
  document.getElementById("island-name").textContent =
    island.island.display_name + " (" + island.island.id + ", " + island.profile + ")";
  document.getElementById("f-display-name").value = island.island.display_name;
  document.getElementById("f-country").value = island.island.country;
}

function renderServicesToggles() {
  var container = document.getElementById("services-toggles");
  container.innerHTML = "";
  var enabled = island.services.enabled;
  Object.keys(enabled).forEach(function (name) {
    var label = document.createElement("label");
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!enabled[name];
    cb.addEventListener("change", function () {
      enabled[name] = cb.checked;
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode(" " + name));
    container.appendChild(label);
  });
  document.getElementById("f-assoc-name").value = island.services.portal_association_name || "";
  document.getElementById("f-assoc-contact").value = island.services.portal_operator_contact || "";
}

function renderFederationToggles() {
  var container = document.getElementById("federation-toggles");
  container.innerHTML = "";
  island.federation.items.forEach(function (item) {
    var label = document.createElement("label");
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!item.share;
    cb.addEventListener("change", function () {
      item.share = cb.checked;
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode(" " + item.name + " (" + item.priority_class + ")"));
    container.appendChild(label);
  });
}

function cellCardHtml(site, cellIndex) {
  var cell = site.cells[cellIndex];
  var div = document.createElement("div");
  div.className = "cell-card";
  div.innerHTML =
    '<label>RAT <select class="c-rat"><option value="lte">lte</option><option value="nr">nr</option></select></label>' +
    '<label>Band <input class="c-band" type="text"></label>' +
    '<label>EARFCN (lte) <input class="c-earfcn" type="number"></label>' +
    '<label>ARFCN (nr) <input class="c-arfcn" type="number"></label>' +
    '<label>PCI <input class="c-pci" type="number"></label>' +
    '<label>Bandwidth (MHz) <input class="c-bw" type="number" step="0.1"></label>' +
    '<label>TX power (dBm, blank = unknown/virtual) <input class="c-txpower" type="number" step="0.1"></label>' +
    '<label>Azimuth (deg, blank = unknown) <input class="c-azimuth" type="number"></label>' +
    '<label>Antenna notes <input class="c-notes" type="text"></label>' +
    '<label>Upload measured CSV (lat,lon,rsrp,rsrq,timestamp) <input class="c-csv" type="file" accept=".csv"></label>' +
    '<button type="button" class="c-upload">Upload</button>' +
    (cell.measured_points && cell.measured_points.file_ref
      ? '<div class="hint">measured: ' + cell.measured_points.file_ref + "</div>"
      : "");

  div.querySelector(".c-rat").value = cell.rat;
  div.querySelector(".c-band").value = cell.band;
  div.querySelector(".c-earfcn").value = cell.earfcn === null ? "" : cell.earfcn;
  div.querySelector(".c-arfcn").value = cell.arfcn === null ? "" : cell.arfcn;
  div.querySelector(".c-pci").value = cell.pci;
  div.querySelector(".c-bw").value = cell.bandwidth_mhz;
  div.querySelector(".c-txpower").value = cell.tx_power_dbm === null ? "" : cell.tx_power_dbm;
  div.querySelector(".c-azimuth").value = cell.azimuth_deg === null ? "" : cell.azimuth_deg;
  div.querySelector(".c-notes").value = cell.antenna_notes || "";

  div.querySelector(".c-rat").addEventListener("change", function (e) {
    cell.rat = e.target.value;
  });
  div.querySelector(".c-band").addEventListener("input", function (e) {
    cell.band = e.target.value;
  });
  div.querySelector(".c-earfcn").addEventListener("input", function (e) {
    cell.earfcn = numOrNull(e.target);
  });
  div.querySelector(".c-arfcn").addEventListener("input", function (e) {
    cell.arfcn = numOrNull(e.target);
  });
  div.querySelector(".c-pci").addEventListener("input", function (e) {
    cell.pci = numOrNull(e.target) || 0;
  });
  div.querySelector(".c-bw").addEventListener("input", function (e) {
    cell.bandwidth_mhz = numOrNull(e.target) || 1;
  });
  div.querySelector(".c-txpower").addEventListener("input", function (e) {
    cell.tx_power_dbm = numOrNull(e.target);
  });
  div.querySelector(".c-azimuth").addEventListener("input", function (e) {
    cell.azimuth_deg = numOrNull(e.target);
  });
  div.querySelector(".c-notes").addEventListener("input", function (e) {
    cell.antenna_notes = e.target.value;
  });
  div.querySelector(".c-upload").addEventListener("click", function () {
    var fileInput = div.querySelector(".c-csv");
    if (!fileInput.files.length) return;
    var file = fileInput.files[0];
    file.arrayBuffer().then(function (buf) {
      authedPost("/api/measured/" + site.id + "-" + cellIndex, buf)
        .then(function (r) {
          return r.json();
        })
        .then(function (result) {
          showResult(result);
          if (result.ok) refreshDraftStatus();
        });
    });
  });

  return div;
}

function renderSiteForm() {
  var form = document.getElementById("site-form");
  if (selectedSiteIndex === null) {
    form.hidden = true;
    return;
  }
  form.hidden = false;
  var site = island.sites[selectedSiteIndex];
  document.getElementById("site-name").value = site.name;
  document.getElementById("site-height").value = site.height_m === null ? "" : site.height_m;
  renderCellsList();
}

// Only rebuilds the cells list -- called after "add cell" too, which
// must NOT also re-touch site-name/site-height (those are being live-
// edited via wireSiteInputs() below, not read back on submit; stomping
// them back to the model's last-saved value mid-edit was 2.1-d's own
// first bug, caught by verify-console.js's own live-browser run).
function renderCellsList() {
  var site = island.sites[selectedSiteIndex];
  var list = document.getElementById("cells-list");
  list.innerHTML = "";
  site.cells.forEach(function (_c, i) {
    list.appendChild(cellCardHtml(site, i));
  });
}

// -- map --------------------------------------------------------------

function markerColorFor(index) {
  return index === selectedSiteIndex ? "#a01818" : "#1a7a1a";
}

function refreshMarkers() {
  markers.forEach(function (m) {
    m.remove();
  });
  markers = [];
  island.sites.forEach(function (site, i) {
    if (site.lat === null || site.lon === null) return;
    var marker = new maplibregl.Marker({ draggable: true, color: markerColorFor(i) })
      .setLngLat([site.lon, site.lat])
      .addTo(map);
    marker.getElement().addEventListener("click", function (e) {
      e.stopPropagation();
      selectedSiteIndex = i;
      renderSiteForm();
      refreshMarkers();
    });
    marker.on("dragend", function () {
      var lngLat = marker.getLngLat();
      site.lat = lngLat.lat;
      site.lon = lngLat.lng;
    });
    markers.push(marker);
  });
}

function addSiteAt(lat, lon) {
  var n = island.sites.length + 1;
  island.sites.push({
    id: "site-" + n,
    name: "New site " + n,
    lat: lat,
    lon: lon,
    height_m: 20,
    cells: [],
  });
  selectedSiteIndex = island.sites.length - 1;
  refreshMarkers();
  renderSiteForm();
}

// -- coverage layers ----------------------------------------------------

function ensureHatchPattern() {
  if (map.hasImage("hatch")) return;
  var size = 16;
  var canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  var ctx = canvas.getContext("2d");
  ctx.strokeStyle = "#a01818";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(0, size);
  ctx.lineTo(size, 0);
  ctx.stroke();
  map.addImage("hatch", ctx.getImageData(0, 0, size, size));
}

function loadPredictedCoverage() {
  fetch("/api/coverage/predicted")
    .then(function (r) {
      return r.json();
    })
    .then(function (fc) {
      if (map.getSource("predicted")) {
        map.getSource("predicted").setData(fc);
      } else {
        ensureHatchPattern();
        map.addSource("predicted", { type: "geojson", data: fc });
        map.addLayer({
          id: "predicted-fill",
          type: "fill",
          source: "predicted",
          paint: { "fill-pattern": "hatch", "fill-opacity": 0.6 },
        });
        map.addLayer({
          id: "predicted-outline",
          type: "line",
          source: "predicted",
          paint: { "line-color": "#a01818", "line-width": 1 },
        });
      }
      document.getElementById("predicted-legend").textContent =
        "predicted (model: " + fc.model + ") — not measured";
    });
}

function loadMeasuredForAllCells() {
  var features = [];
  var pending = 0;
  island.sites.forEach(function (site) {
    site.cells.forEach(function (cell, ci) {
      if (!cell.measured_points || !cell.measured_points.file_ref) return;
      pending++;
      fetch("/api/coverage/measured/" + site.id + "-" + ci)
        .then(function (r) {
          return r.json();
        })
        .then(function (fc) {
          features = features.concat(fc.features);
          pending--;
          if (pending === 0) setMeasuredSource(features);
        });
    });
  });
  if (pending === 0) setMeasuredSource(features);
}

function setMeasuredSource(features) {
  var fc = { type: "FeatureCollection", features: features };
  if (map.getSource("measured")) {
    map.getSource("measured").setData(fc);
  } else {
    map.addSource("measured", { type: "geojson", data: fc });
    map.addLayer({
      id: "measured-points",
      type: "circle",
      source: "measured",
      paint: { "circle-radius": 4, "circle-color": "#1a4d7a", "circle-opacity": 0.8 },
    });
  }
}

// -- preview / draft ------------------------------------------------------
// "Apply" (signing + render + restart) is host-only now (RFC-0006 D5) --
// the browser can only stage a validated draft (POST /api/draft) and see
// whether one is pending (GET /api/draft); see server.py's own header
// comment and island_init/apply.py.

function showResult(result) {
  var out = document.getElementById("result");
  if (result.ok) {
    var text = result.diff || "no changes";
    if (result.pending) {
      text += "\n\nsaved as a pending draft (staged " + result.staged_at + ") -- " +
        "run ./island.sh apply on the node to sign and apply it.";
    }
    out.textContent = text;
  } else if (result.error) {
    out.textContent = "error: " + result.error;
  } else {
    out.textContent = (result.issues || [])
      .map(function (i) {
        return (i.line ? "line " + i.line + ": " : "") + i.field + ": " + i.message;
      })
      .join("\n");
  }
}

function refreshDraftStatus() {
  fetch("/api/draft")
    .then(function (r) {
      return r.json();
    })
    .then(function (status) {
      var el = document.getElementById("draft-status");
      el.textContent = status.pending
        ? "Pending draft staged at " + status.staged_at + " -- awaiting island.sh apply on the node."
        : "No pending draft.";
    });
}

function currentCandidate() {
  return island; // already fully in sync -- see wireStaticInputs()/wireSiteInputs()
}

// Static inputs exist once in the DOM (they're just hidden/shown, never
// recreated), so they're wired exactly once, here -- not inside a
// render*() function, which would stack a duplicate listener on every
// re-render.
function wireStaticInputs() {
  document.getElementById("f-display-name").addEventListener("input", function (e) {
    island.island.display_name = e.target.value;
  });
  document.getElementById("f-country").addEventListener("input", function (e) {
    island.island.country = e.target.value.toUpperCase();
  });
  document.getElementById("f-assoc-name").addEventListener("input", function (e) {
    island.services.portal_association_name = textOrNull(e.target);
  });
  document.getElementById("f-assoc-contact").addEventListener("input", function (e) {
    island.services.portal_operator_contact = textOrNull(e.target);
  });
  document.getElementById("site-name").addEventListener("input", function (e) {
    if (selectedSiteIndex !== null) island.sites[selectedSiteIndex].name = e.target.value;
  });
  document.getElementById("site-height").addEventListener("input", function (e) {
    if (selectedSiteIndex !== null) island.sites[selectedSiteIndex].height_m = numOrNull(e.target);
  });
  var tokenInput = document.getElementById("f-operator-token");
  tokenInput.value = getOperatorToken();
  tokenInput.addEventListener("input", function (e) {
    setOperatorToken(e.target.value);
  });
}

function reload() {
  fetch("/api/island")
    .then(function (r) {
      return r.json();
    })
    .then(function (data) {
      island = data;
      selectedSiteIndex = null;
      renderIdentity();
      renderServicesToggles();
      renderFederationToggles();
      renderSiteForm();
      refreshMarkers();
      loadPredictedCoverage();
      loadMeasuredForAllCells();
      refreshDraftStatus();
    });
}

document.getElementById("btn-add-cell").addEventListener("click", function () {
  if (selectedSiteIndex === null) return;
  island.sites[selectedSiteIndex].cells.push({
    rat: "lte",
    band: "",
    earfcn: null,
    arfcn: null,
    pci: 0,
    bandwidth_mhz: 5,
    tx_power_dbm: null,
    azimuth_deg: null,
    antenna_notes: "",
    predicted_coverage: null,
    measured_points: null,
  });
  renderCellsList();
});

document.getElementById("btn-preview").addEventListener("click", function () {
  authedPost("/api/preview", JSON.stringify(currentCandidate()))
    .then(function (r) {
      return r.json();
    })
    .then(showResult);
});

document.getElementById("btn-save-draft").addEventListener("click", function () {
  authedPost("/api/draft", JSON.stringify(currentCandidate()))
    .then(function (r) {
      return r.json();
    })
    .then(function (result) {
      showResult(result);
      if (result.ok) refreshDraftStatus();
    });
});

document.getElementById("toggle-predicted").addEventListener("change", function (e) {
  if (map.getLayer("predicted-fill")) {
    var vis = e.target.checked ? "visible" : "none";
    map.setLayoutProperty("predicted-fill", "visibility", vis);
    map.setLayoutProperty("predicted-outline", "visibility", vis);
  }
});

document.getElementById("toggle-measured").addEventListener("change", function (e) {
  if (map.getLayer("measured-points")) {
    map.setLayoutProperty("measured-points", "visibility", e.target.checked ? "visible" : "none");
  }
});

// -- init ---------------------------------------------------------------

wireStaticInputs();

var protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

map = new maplibregl.Map({
  container: "map",
  style: "/style.json",
  center: [0, 20],
  zoom: 1,
});
map.addControl(new maplibregl.NavigationControl());
map.on("click", function (e) {
  addSiteAt(e.lngLat.lat, e.lngLat.lng);
});
map.on("load", function () {
  loadPredictedCoverage();
  loadMeasuredForAllCells();
});

reload();
