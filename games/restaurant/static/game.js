/* Maison Cinq floor UI: polls /api/state, draws the room, talks + acts. */
(function () {
  "use strict";

  var W = 40, H = 24; // floor grid units (sim coordinates)
  var canvas = document.getElementById("floor");
  var ctx = canvas.getContext("2d");
  var cursor = 0;
  var selected = null;
  var bubbles = {}; // entity id -> {text, tick}
  var passive = false;
  var latest = null;
  var toastTimer = null;
  var prevPos = {}; // entity id -> {x, y} for walk detection
  var seenIds = {}; // arrival shimmer, once per entity
  var sheets = {}; // manifest name -> {def, img} (empty until art loads)
  var lastActionKey = "";

  var ZONES = [
    { name: "Entrance", x: 0, y: 8, w: 6, h: 8, tint: "rgba(120,90,40,0.12)" },
    { name: "Dining hall", x: 10, y: 4, w: 20, h: 16, tint: "rgba(150,60,50,0.10)" },
    { name: "Kitchen", x: 33, y: 16, w: 7, h: 8, tint: "rgba(90,140,180,0.12)" },
    { name: "Bar", x: 29, y: 0, w: 8, h: 7, tint: "rgba(60,140,90,0.12)" }
  ];

  function sx(x) { return x / W * canvas.width; }
  function sy(y) { return y / H * canvas.height; }

  function post(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    }).then(function (resp) {
      if (!resp.ok) {
        return resp.json().then(function (err) {
          throw new Error((err && err.detail) || ("HTTP " + resp.status));
        });
      }
      return resp.json();
    });
  }

  function esc(text) {
    return String(text).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function toast(message) {
    var el = document.getElementById("toast");
    el.textContent = message;
    el.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 2600);
  }

  function colorFor(entity) {
    if (entity.kind === "player") return "#c0392b";
    if (entity.kind === "staff") return "#2e8b74";
    return "#d8a13c";
  }

  // -- generated art: manifest-driven, shapes as fallback --------------------

  function isFeminine(id) {
    var h = 0;
    for (var i = 0; i < id.length; i++) h = ((h * 31) + id.charCodeAt(i)) | 0;
    return ((h >>> 0) % 2) === 0;
  }

  function loadSprites() {
    fetch("/static/assets/manifest.json").then(function (resp) {
      if (!resp.ok) return null;
      return resp.json();
    }).then(function (manifest) {
      (manifest || []).forEach(function (entry) {
        if (!entry || !entry.name || !entry.file) return;
        var img = new Image();
        img.onload = (function (e, im) {
          return function () { sheets[e.name] = { def: e, img: im }; };
        })(entry, img);
        img.src = "/static/" + entry.file;
      });
    }).catch(function () { /* shapes stay */ });
  }

  // Draw one manifest sprite/frame anchored bottom-center at feet.
  function drawSheet(name, frame, feetX, feetY, flip) {
    var s = sheets[name];
    if (!s || !s.img.complete || !s.img.naturalWidth) return false;
    var d = s.def;
    var dh = d.draw_height || 40;
    var sw = d.cell_w || d.w, sh = d.cell_h || d.h;
    if (!sw || !sh) return false;
    var dw = dh * sw / sh;
    var sx0 = (frame || 0) * sw;
    if (sx0 + sw > s.img.naturalWidth + 1) return false;
    ctx.save();
    if (flip) {
      ctx.translate(feetX, 0);
      ctx.scale(-1, 1);
      ctx.drawImage(s.img, sx0, 0, sw, sh, -dw / 2, feetY - dh, dw, dh);
    } else {
      ctx.drawImage(s.img, sx0, 0, sw, sh, feetX - dw / 2, feetY - dh, dw, dh);
    }
    ctx.restore();
    return true;
  }

  // Pick (sheet, frame) for an entity given live state.
  function poseFor(entity, state, moving) {
    var role = entity.role;
    if (entity.kind === "player") {
      if (!moving) return { sheet: "player", frame: 0 };
      return { sheet: "player-walk", frame: ((state.tick >> 2) % 2) + 1 };
    }
    if (role === "chef") {
      var cooking = (state.orders || []).some(function (o) { return o.state === "cooking"; });
      return cooking ? { sheet: "chef-action", frame: 1 } : { sheet: "chef", frame: 0 };
    }
    if (role === "waiter" || role === "host") {
      return moving ? { sheet: "waiter-action", frame: 1 } : { sheet: "waiter", frame: 0 };
    }
    if (role === "manager") return { sheet: "manager", frame: 0 };
    if (role === "sommelier") return { sheet: "sommelier", frame: 0 };
    var fem = isFeminine(entity.id);
    if (entity.flow === "seated") return { sheet: "customers-seated", frame: fem ? 3 : 2 };
    if (entity.flow === "eating") return { sheet: "customers-seated", frame: fem ? 1 : 0 };
    return { sheet: fem ? "customer-f" : "customer-m", frame: 0 };
  }

  function draw() {
    var state = latest;
    if (!state) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#2b2118";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    var bg = sheets["bg-dining"];
    if (bg && bg.img.complete && bg.img.naturalWidth) {
      ctx.drawImage(bg.img, 0, 0, canvas.width, canvas.height);
    }
    // zones with tints
    ZONES.forEach(function (z) {
      ctx.fillStyle = z.tint;
      ctx.fillRect(sx(z.x), sy(z.y), sx(z.w), sy(z.h));
      ctx.strokeStyle = "#5a4c38";
      ctx.lineWidth = 1;
      ctx.strokeRect(sx(z.x), sy(z.y), sx(z.w), sy(z.h));
      ctx.font = "11px Georgia, serif";
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(20,14,8,0.85)";
      ctx.strokeText(z.name, sx(z.x) + 4, sy(z.y) + 14);
      ctx.fillStyle = "#d8c89a";
      ctx.fillText(z.name, sx(z.x) + 4, sy(z.y) + 14);
    });
    drawProps();
    // dressed tables: cloth + plates + candle, cloche when food is ready
    var readyTables = {}, billedTables = {};
    (state.orders || []).forEach(function (o) {
      if (o.state === "ready") readyTables[o.table] = true;
      if (o.state === "served") billedTables[o.table] = true;
    });
    (state.tables || []).forEach(function (t) {
      var x = sx(t.x), y = sy(t.y);
      ctx.fillStyle = t.guest ? "#8a6d2f" : "#4a3d2c";
      ctx.beginPath();
      ctx.arc(x, y, 14, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#efe6d2";
      ctx.beginPath();
      ctx.arc(x, y, 10, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#b9ac90";
      [[-4, -3], [4, -3], [-4, 4], [4, 4]].forEach(function (o) {
        ctx.beginPath();
        ctx.arc(x + o[0], y + o[1], 2.2, 0, Math.PI * 2);
        ctx.fill();
      });
      if (drawSheet("candle", 0, x - 8, y - 8, false)) {
        /* art candle replaces the rect */
      } else {
        ctx.fillStyle = "#e8a13c";
        ctx.fillRect(x - 1, y - 12, 2, 5);
      }
      if (readyTables[t.id]) drawSheet("cloche", 0, x, y - 2, false);
      if (billedTables[t.id]) drawSheet("bill", 0, x + 12, y + 6, false);
      ctx.font = "9px sans-serif";
      ctx.textAlign = "center";
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(20,14,8,0.85)";
      ctx.strokeText(t.id, x, y + 26);
      ctx.fillStyle = "#e8dcc2";
      ctx.fillText(t.id, x, y + 26);
      ctx.textAlign = "left";
    });
    // event flashes: expanding rings at seat/serve/pay spots
    (state.events || []).forEach(function (e) {
      var age = state.tick - e.tick;
      if (age < 0 || age > 25) return;
      var colors = { seat: "#7fd08a", serve: "#e8c13c", pay: "#7fb8d0" };
      ctx.strokeStyle = colors[e.kind] || "#ffffff";
      ctx.lineWidth = 2;
      ctx.globalAlpha = 1 - age / 25;
      ctx.beginPath();
      ctx.arc(sx(e.x), sy(e.y), 10 + age * 1.6, 0, Math.PI * 2);
      ctx.stroke();
      if (e.kind === "pay") drawSheet("coins", 0, sx(e.x), sy(e.y) - 12, false);
      if (e.kind === "serve") drawSheet("star", 0, sx(e.x), sy(e.y) - 12, false);
      ctx.globalAlpha = 1;
    });
    drawEntities(state);
  }

  function drawProps() {
    ctx.fillStyle = "#5a4c38";
    for (var i = 0; i < 4; i++) {
      ctx.beginPath();
      ctx.arc(sx(30 + i * 1.6), sy(2.2), 3, 0, Math.PI * 2);
      ctx.fill();
    }
    drawSheet("wine", 0, sx(32), sy(1.6), false); // bottle on the bar
    ctx.fillStyle = "#3e6b4f";
    ctx.fillRect(sx(29.5), sy(0.6), sx(6), 4);
    ctx.fillStyle = "#6b5f4c";
    ctx.fillRect(sx(33.5), sy(17.5), sx(5.5), 5); // kitchen pass
    ctx.fillStyle = "#7a1f2b";
    ctx.fillRect(sx(0.6), sy(11.6), sx(2), 3); // velvet rope
  }

  function drawGlyph(e, x, y) {
    ctx.fillStyle = "#f0e7d5";
    if (e.role === "chef") {
      ctx.beginPath();
      ctx.arc(x, y - 9, 4.5, Math.PI, 0);
      ctx.fill();
      ctx.fillRect(x - 4.5, y - 9, 9, 2.5);
    } else if (e.role === "waiter") {
      ctx.fillRect(x - 8, y - 12, 12, 2);
      ctx.beginPath();
      ctx.arc(x - 2, y - 13.5, 2, 0, Math.PI * 2);
      ctx.fill();
    } else if (e.role === "manager") {
      ctx.font = "9px sans-serif";
      ctx.fillText("*", x + 6, y - 6);
    } else if (e.role === "sommelier") {
      ctx.strokeStyle = "#f0e7d5";
      ctx.beginPath();
      ctx.arc(x + 7, y - 7, 2.5, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  function drawEntities(state) {
    var placed = [];
    (state.entities || []).forEach(function (e, index) {
      var x = sx(e.x), y = sy(e.y);
      // walk bob / idle sway: movement you can see
      var prev = prevPos[e.id] || { x: e.x, y: e.y, flip: false };
      var moving = Math.abs(prev.x - e.x) + Math.abs(prev.y - e.y) > 0.01;
      var flip = prev.flip;
      if (e.x < prev.x - 0.01) flip = true;
      else if (e.x > prev.x + 0.01) flip = false;
      prevPos[e.id] = { x: e.x, y: e.y, flip: flip };
      var bob = Math.sin((state.tick + index * 7) * 0.35) * (moving ? 2.6 : 0.9);
      y += bob;
      // arrival shimmer, once per entity
      if (!seenIds[e.id]) {
        seenIds[e.id] = state.tick;
      }
      var age = state.tick - seenIds[e.id];
      if (age >= 0 && age < 20) {
        ctx.strokeStyle = "#e8dcc2";
        ctx.globalAlpha = 1 - age / 20;
        ctx.beginPath();
        ctx.arc(x, y, 10 + age * 1.2, 0, Math.PI * 2);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      ctx.fillStyle = "rgba(0,0,0,0.35)";
      ctx.beginPath();
      ctx.ellipse(x, y + 7 - bob * 0.4, 9, 3.5, 0, 0, Math.PI * 2);
      ctx.fill();
      var pose = poseFor(e, state, moving);
      if (!drawSheet(pose.sheet, pose.frame, x, y + 7, flip)) {
        ctx.fillStyle = colorFor(e);
        ctx.beginPath();
        ctx.arc(x, y, 8, 0, Math.PI * 2);
        ctx.fill();
        drawGlyph(e, x, y);
      }
      if (selected === e.id) {
        ctx.strokeStyle = "#f0e7d5";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, 12, 0, Math.PI * 2);
        ctx.stroke();
      }
      // name pill, staggered when crowded (strangers stay unnamed)
      var first = (e.id !== "you" && e.known === false) ? "Stranger" : e.name.split(" ")[0];
      ctx.font = "10px sans-serif";
      var w = ctx.measureText(first).width + 10;
      var lx = x + 12, ly = y - 6;
      placed.forEach(function (p) {
        if (Math.abs(p.x - lx) < w && Math.abs(p.y - ly) < 14) ly = p.y - 14;
      });
      placed.push({ x: lx, y: ly });
      ctx.fillStyle = "rgba(20,14,8,0.78)";
      ctx.fillRect(lx - 5, ly - 10, w, 14);
      ctx.fillStyle = "#f0e7d5";
      ctx.fillText(first, lx, ly + 1);
      var bubble = bubbles[e.id];
      if (bubble && state.tick - bubble.tick < 60) {
        drawBubble(x, y - 16 - Math.min(10, (state.tick - bubble.tick) / 3), bubble.text);
      }
    });
  }

  function drawBubble(x, y, text) {
    var words = String(text).split(" ");
    var lines = [""];
    words.forEach(function (w) {
      var last = lines[lines.length - 1];
      if ((last + " " + w).length > 34) lines.push(w);
      else lines[lines.length - 1] = (last + " " + w).trim();
    });
    lines = lines.slice(0, 3);
    ctx.font = "11px sans-serif";
    var width = 0;
    lines.forEach(function (line) {
      width = Math.max(width, ctx.measureText(line).width);
    });
    width += 14;
    var height = lines.length * 14 + 10;
    var bx = Math.min(Math.max(x - width / 2, 4), canvas.width - width - 4);
    ctx.fillStyle = "rgba(255,253,248,0.94)";
    ctx.strokeStyle = "#8a7a5c";
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(bx, y - height, width, height, 4);
    else ctx.rect(bx, y - height, width, height);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#241d16";
    lines.forEach(function (line, i) {
      ctx.fillText(line, bx + 7, y - height + 16 + i * 14);
    });
  }

  function render(state) {
    latest = state;
    passive = state.mode !== "active";
    document.getElementById("mode").value = state.mode;
    document.getElementById("role").value = state.role;
    document.getElementById("lang").value = state.lang;
    document.getElementById("st-revenue").textContent = "€" + state.stats.revenue;
    document.getElementById("st-rating").textContent = state.stats.rating.toFixed(1);
    document.getElementById("st-served").textContent = state.stats.served;
    document.getElementById("st-waiting").textContent = state.waiting;
    var key = document.getElementById("key");
    key.textContent = state.key.fake ? "test LLM (fake)"
      : state.key.live ? "live LLM " + state.key.show : "LLM required";
    key.title = state.key.hint || state.key.show || "";
    (state.bubbles || []).forEach(function (b) {
      bubbles[b.by] = { text: b.text, tick: state.tick };
    });
    cursor = state.delivered_cursor || cursor;
    var orders = document.getElementById("order-list");
    orders.innerHTML = "";
    if (!state.orders || !state.orders.length) {
      orders.innerHTML = '<li class="dim">None yet.</li>';
    }
    (state.orders || []).slice(-6).reverse().forEach(function (o) {
      var li = document.createElement("li");
      var who = o.seat ? " (" + nameOf(state, o.seat) + ")" : "";
      li.textContent = o.id + " · " + o.table + who + " · " + o.dish + " — " + o.state;
      orders.appendChild(li);
    });
    renderNearby(state);
    renderTranscript(state);
    renderPerson(state);
    renderChat(state);
    draw();
  }

  function nameOf(state, id) {
    if (id === "you") return "you";
    var found = (state.entities || []).filter(function (e) { return e.id === id; })[0];
    if (!found) {
      var thread = (state.chats || {})[id];
      return (thread && thread.name) ? thread.name.split(" ")[0] : "Stranger";
    }
    if (found.known === false) return "Stranger";
    return found.name.split(" ")[0];
  }

  function renderNearby(state) {
    var box = document.getElementById("nearby");
    var spots = state.nearby || [];
    if (!spots.length) {
      box.innerHTML = '<p class="dim">Walk to the bar, the pass, the host stand, or a table.</p>';
      return;
    }
    box.innerHTML = "";
    spots.forEach(function (spot) {
      var div = document.createElement("div");
      div.className = "spot";
      var head = document.createElement("strong");
      head.textContent = spot.label;
      div.appendChild(head);
      var row = document.createElement("div");
      row.className = "actions";
      (spot.actions || []).forEach(function (spec) {
        var button = document.createElement("button");
        button.textContent = spec.label;
        button.disabled = passive;
        button.onclick = function () { fire(spec.action, spec.params || {}); };
        row.appendChild(button);
      });
      div.appendChild(row);
      box.appendChild(div);
    });
  }

  function renderTranscript(state) {
    var log = document.getElementById("log");
    var lines = (state.transcript || []).slice(-12).reverse();
    if (!lines.length) {
      log.innerHTML = '<li class="dim">Quiet… for now.</li>';
      return;
    }
    log.innerHTML = "";
    lines.forEach(function (entry) {
      var li = document.createElement("li");
      var heard = (entry.heard_by || []).map(function (id) { return nameOf(state, id); });
      li.innerHTML = '<span class="tick">t' + entry.tick + "</span> " +
        '<span class="who">' + esc(nameOf(state, entry.by)) + ":</span> " +
        esc(entry.text) +
        (heard.length ? ' <span class="heard">→ heard by ' + esc(heard.join(", ")) + "</span>" : "");
      log.appendChild(li);
    });
  }

  function threadLabel(state, id) {
    var thread = (state.chats || {})[id];
    if (thread && thread.name) return thread.name.split(" ")[0];
    return nameOf(state, id);
  }

  function renderChat(state) {
    var box = document.getElementById("threads");
    box.innerHTML = "";
    var ids = Object.keys(state.chats || {});
    if (selected && ids.indexOf(selected) < 0 && selected !== "you") {
      ids.push(selected); // open thread, no messages yet
    }
    ids.forEach(function (id) {
      var thread = (state.chats || {})[id] || {};
      var button = document.createElement("button");
      button.textContent = threadLabel(state, id);
      if (id === selected) button.className = "active";
      else if (!thread.known) button.className = "stranger";
      button.onclick = function () { selected = id; render(state); };
      box.appendChild(button);
    });
    var log = document.getElementById("chat-log");
    var thread = (state.chats || {})[selected];
    if (!thread || !thread.messages || !thread.messages.length) {
      log.innerHTML = selected
        ? '<li class="dim">No messages yet — say hello.</li>'
        : '<li class="dim">Click a person on the floor to talk.</li>';
    } else {
      log.innerHTML = "";
      thread.messages.forEach(function (m) {
        var li = document.createElement("li");
        var mine = m.by === "you";
        li.innerHTML = '<span class="' + (mine ? "me" : "them") + '">' +
          esc(mine ? "You" : threadLabel(state, selected)) + ":</span> " +
          esc(m.text);
        log.appendChild(li);
      });
      log.scrollTop = log.scrollHeight;
    }
    document.getElementById("say").disabled = passive || !selected;
    document.getElementById("talk").disabled = passive || !selected;
  }

  function nameOfState() { return latest; }

  // action -> inline picker spec fed by live state
  function pickerFor(action, state) {
    if (action === "serve_dish" || action === "cook_dish" || action === "rush_order") {
      var open = (state.orders || []).filter(function (o) {
        return o.state === "ready" || o.state === "ordered" || o.state === "cooking";
      }).map(function (o) { return o.id + " · " + o.dish + " (" + o.state + ")"; });
      return open.length ? { key: "order", label: "Order", options: open, valueOf: function (s) { return s.split(" ")[0]; } } : null;
    }
    if (action === "take_order" || action === "comp_dish") {
      var busy = (state.tables || []).filter(function (t) { return t.guest; }).map(function (t) { return t.id; });
      return busy.length ? { key: "table", label: "Table", options: busy, valueOf: function (s) { return s; } } : null;
    }
    if (action === "order_dish") {
      return { key: "dish", label: "Dish", options: state.menu || [], valueOf: function (s) { return s; } };
    }
    return { key: null };
  }

  function renderPerson(state) {
    var card = document.getElementById("person-card");
    var none = document.getElementById("person-none");
    var entity = (state.entities || []).filter(function (e) { return e.id === selected; })[0];
    if (!entity) {
      card.hidden = true;
      none.hidden = false;
      return;
    }
    card.hidden = false;
    none.hidden = true;
    var stranger = entity.id !== "you" && entity.known === false;
    document.getElementById("p-name").textContent =
      stranger ? "Stranger" : entity.name;
    document.getElementById("p-role").textContent = "· " + entity.role + " · " + entity.kind;
    document.getElementById("p-langs").textContent =
      (stranger ? "You haven't been introduced — say hello in Chat. "
                : "Speaks " + (entity.languages || ["english"]).join(", "));
    var groupLine = "";
    if (entity.group && entity.group !== "solo") {
      groupLine = "Here with " + (entity.group === "couple" ? "their partner" :
        entity.group === "family" ? "family" : "friends");
    }
    document.getElementById("p-group").textContent = groupLine;
    // Rebuild action buttons only when the set changes, so an open
    // picker survives the twice-a-second refresh.
    var key = (state.actions || []).join(",") + "|" + (passive ? "p" : "a");
    var box = document.getElementById("actions");
    if (key !== lastActionKey) {
      lastActionKey = key;
      box.innerHTML = "";
      (state.actions || []).forEach(function (action) {
        var button = document.createElement("button");
        button.textContent = action.replace(/_/g, " ");
        button.disabled = passive;
        button.onclick = function () { doAct(action); };
        box.appendChild(button);
      });
      var stale = document.getElementById("picker-row");
      if (stale) stale.remove();
    }
  }

  function doAct(action) {
    var spec = pickerFor(action, latest);
    if (spec === null) {
      toast("Nothing to do right now.");
      return;
    }
    if (spec.key === null) {
      fire(action, {});
      return;
    }
    var old = document.getElementById("picker-row");
    if (old) old.remove();
    var row = document.createElement("div");
    row.className = "picker";
    row.id = "picker-row";
    var select = document.createElement("select");
    select.setAttribute("aria-label", spec.label);
    spec.options.forEach(function (opt) {
      var el = document.createElement("option");
      el.textContent = opt;
      select.appendChild(el);
    });
    var go = document.createElement("button");
    go.textContent = "Go";
    go.onclick = function () {
      var params = {};
      params[spec.key] = spec.valueOf(select.value);
      row.remove();
      fire(action, params);
    };
    var cancel = document.createElement("button");
    cancel.textContent = "×";
    cancel.className = "cancel";
    cancel.onclick = function () { row.remove(); };
    row.appendChild(select);
    row.appendChild(go);
    row.appendChild(cancel);
    document.getElementById("person-card").appendChild(row);
    select.focus();
  }

  function fire(action, params) {
    post("/api/act", { action: action, params: params }).then(function (out) {
      if (out && out.result && out.result.message) toast(out.result.message);
      return refresh();
    }).catch(function (err) { toast(err.message); });
  }

  function refresh() {
    return fetch("/api/state?cursor=" + cursor).then(function (resp) {
      return resp.json();
    }).then(render).catch(function () { /* server hiccup: retry next poll */ });
  }

  canvas.addEventListener("click", function (event) {
    if (passive) return;
    var rect = canvas.getBoundingClientRect();
    var px = (event.clientX - rect.left) / rect.width * W;
    var py = (event.clientY - rect.top) / rect.height * H;
    fetch("/api/state?cursor=" + cursor).then(function (resp) { return resp.json(); }).then(function (state) {
      var best = null, bestDist = 2.5;
      (state.entities || []).forEach(function (e) {
        var d = Math.hypot(e.x - px, e.y - py);
        if (d < bestDist) { bestDist = d; best = e.id; }
      });
      if (best) {
        selected = best;
        render(state);
      } else {
        post("/api/move", { x: Math.round(px * 10) / 10, y: Math.round(py * 10) / 10 })
          .then(refresh)
          .catch(function (err) { toast(err.message); });
      }
    });
  });

  document.getElementById("say").onclick = function () {
    var input = document.getElementById("talk");
    if (!selected || !input.value.trim()) return;
    post("/api/talk", { to: selected, text: input.value.trim() }).then(function () {
      input.value = "";
      return refresh();
    }).catch(function (err) { toast(err.message); });
  };
  document.getElementById("talk").addEventListener("keydown", function (event) {
    if (event.key === "Enter") document.getElementById("say").click();
  });
  document.getElementById("mode").onchange = function (e) {
    post("/api/mode", { mode: e.target.value }).then(refresh);
  };
  document.getElementById("role").onchange = function (e) {
    post("/api/role", { role: e.target.value }).then(refresh);
  };
  document.getElementById("lang").onchange = function (e) {
    post("/api/lang", { lang: e.target.value }).then(refresh);
  };

  loadSprites();
  setInterval(refresh, 500);
  refresh();
})();
