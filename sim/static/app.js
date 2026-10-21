const state = {
  data: null,
  channel: { type: "public" },
  auto: false,
  autoPoll: null,
  roundFilter: "all",
};

async function apiGet(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

async function apiPost(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

function channelKey(channel) {
  if (channel.type === "public") return "public";
  return `dm:${channel.playerId}`;
}

function buildChannels(data) {
  const channels = [{ type: "public", label: "Public Room" }];
  const players = Object.values(data.players || {});
  for (const player of players) {
    channels.push({ type: "dm", playerId: player.id, label: player.display_name || player.id });
  }
  return channels;
}

function renderChannels(data) {
  const list = document.getElementById("channelList");
  list.innerHTML = "";
  const channels = buildChannels(data);
  const currentKey = channelKey(state.channel);

  for (const channel of channels) {
    const btn = document.createElement("div");
    btn.className = "channel";
    if (channelKey(channel) === currentKey) btn.classList.add("active");
    const left = document.createElement("div");
    left.className = "channel-left";
    if (channel.type === "dm") {
      const avatar = document.createElement("img");
      avatar.className = "avatar";
      avatar.src = getAvatarSrc(channel.playerId);
      avatar.alt = channel.label;
      left.appendChild(avatar);
    }
    const label = document.createElement("div");
    label.textContent = channel.label;
    left.appendChild(label);
    const tag = document.createElement("div");
    tag.className = "status";
    if (channel.type === "dm") {
      const pid = channel.playerId;
      const modelId = data.players?.[pid]?.model_id || "";
      const modelName = data.models?.[modelId] || modelId || "-";
      tag.textContent = modelName.split("/").pop() || modelName;
    } else {
      tag.textContent = "public";
    }
    if (channel.type === "dm" && data.money_holder === channel.playerId) {
      label.textContent = `${channel.label} 💵`;
      btn.classList.add("money-holder");
    }
    btn.appendChild(left);
    btn.appendChild(tag);
    btn.addEventListener("click", () => {
      state.channel = channel.type === "public" ? { type: "public" } : { type: "dm", playerId: channel.playerId };
      renderAll();
    });
    list.appendChild(btn);
  }
}

function getEventsForChannel(data) {
  const channel = state.channel;
  const events = [];
  const days = data.days || [];
  for (const day of days) {
    if (state.roundFilter !== "all" && day.day_number !== state.roundFilter) {
      continue;
    }
    for (const event of day.events || []) {
      if (channel.type === "public") {
        if (event.channel !== "dm" && event.channel !== "agent_raw") {
          events.push({ ...event, round: day.day_number });
        }
      } else if (channel.type === "dm") {
        const player = data.players[channel.playerId];
        const displayName = player?.display_name || player?.id || "";
        if (event.channel === "dm" && (event.to === displayName || event.from === displayName)) {
          events.push({ ...event, round: day.day_number });
        }
      }
    }
  }
  return events;
}

function renderRoundTabs(data) {
  const tabs = document.getElementById("roundTabs");
  tabs.innerHTML = "";
  const days = data.days || [];
  const rounds = days.map((d) => d.day_number).filter((n) => typeof n === "number");
  const latest = rounds.length ? rounds[rounds.length - 1] : "all";
  if (!rounds.includes(state.roundFilter) && state.roundFilter !== "all") {
    state.roundFilter = latest;
  }

  const allTab = document.createElement("button");
  allTab.textContent = "All";
  allTab.className = "round-tab";
  if (state.roundFilter === "all") allTab.classList.add("active");
  allTab.addEventListener("click", () => {
    state.roundFilter = "all";
    renderAll();
  });
  tabs.appendChild(allTab);

  for (const round of rounds) {
    const tab = document.createElement("button");
    tab.textContent = `Round ${round}`;
    tab.className = "round-tab";
    if (state.roundFilter === round) tab.classList.add("active");
    tab.addEventListener("click", () => {
      state.roundFilter = round;
      renderAll();
    });
    tabs.appendChild(tab);
  }
}

function renderFeed(data) {
  const feed = document.getElementById("feed");
  feed.innerHTML = "";
  const events = getEventsForChannel(data);
  if (!events.length) {
    feed.innerHTML = "<div class=\"message\"><div class=\"content\">No messages yet.</div></div>";
    return;
  }

  let currentRound = null;
  for (const event of events) {
    if (event.round !== currentRound) {
      currentRound = event.round;
      const sep = document.createElement("div");
      sep.className = "day-separator";
      sep.textContent = `Round ${currentRound}`;
      feed.appendChild(sep);
    }

    const msg = document.createElement("div");
    msg.className = "message";
    msg.dataset.from = event.from || "";
    const meta = document.createElement("div");
    meta.className = "meta";
    const from = event.from || "";
    const to = event.to ? ` → ${event.to}` : "";
    const metaText = document.createElement("span");
    const pidForMeta = resolvePidFromName(data, from);
    if (pidForMeta && pidForMeta === data.money_holder) {
      metaText.textContent = `${from} 💵${to} · ${event.ts}`;
    } else {
      metaText.textContent = `${from}${to} · ${event.ts}`;
    }
    meta.appendChild(metaText);
    if (pidForMeta) {
      const modelTag = document.createElement("span");
      modelTag.className = "model-tag";
      const modelId = data.players?.[pidForMeta]?.model_id || "";
      const modelName = data.models?.[modelId] || modelId || "-";
      modelTag.textContent = modelName.split("/").pop() || modelName;
      meta.appendChild(modelTag);
    }

    const tag = document.createElement("div");
    tag.className = "tag";
    tag.textContent = event.channel.replace("_", " ");

    const pid = resolvePidFromName(data, from);
    let avatar = null;
    if (pid) {
      avatar = document.createElement("img");
      avatar.className = "message-avatar";
      avatar.alt = from;
      avatar.src = getAvatarSrc(pid);
    } else {
      msg.classList.add("no-avatar");
    }
    if (pid && pid === data.money_holder) {
      msg.classList.add("money-holder");
    }

    const content = document.createElement("div");
    content.className = "content";
    content.innerHTML = renderMarkdown(event.content || "");

    if (avatar) msg.appendChild(avatar);
    msg.appendChild(meta);
    msg.appendChild(tag);
    msg.appendChild(content);
    feed.appendChild(msg);
  }
}

function renderState(data) {
  document.getElementById("stateRound").textContent = data.round_number || 0;
  const roundIndicator = document.getElementById("roundIndicator");
  if (data.game_over) {
    roundIndicator.textContent = "Game Over";
  } else if (data.discussion_done) {
    roundIndicator.textContent = `Round ${data.round_number || 0} · Ready to Vote`;
  } else {
    roundIndicator.textContent = `Round ${data.round_number || 0} · Discussion`;
  }
  document.getElementById("runRoundBtn").disabled = Boolean(data.game_over || data.discussion_done);
  document.getElementById("startVoteBtn").disabled = Boolean(data.game_over || !data.discussion_done);
  document.getElementById("autoBtn").disabled = Boolean(data.game_over);
  updateAutoButton();

  const aliveWrap = document.getElementById("stateAlive");
  aliveWrap.innerHTML = "";
  for (const pid of data.alive_players || []) {
    const pill = document.createElement("span");
    pill.className = "state-pill";
    pill.textContent = data.players[pid]?.display_name || pid;
    aliveWrap.appendChild(pill);
  }

  const elimWrap = document.getElementById("stateEliminated");
  elimWrap.innerHTML = "";
  for (const pid of data.eliminated_players || []) {
    const pill = document.createElement("span");
    pill.className = "state-pill";
    pill.textContent = data.players[pid]?.display_name || pid;
    elimWrap.appendChild(pill);
  }

  const moneyToggle = document.getElementById("moneyToggle");
  const moneyHolder = data.players[data.money_holder]?.display_name || data.money_holder || "";
  const moneyLabel = document.getElementById("stateMoney");
  moneyLabel.textContent = moneyToggle.checked ? moneyHolder : "Hidden";

  const winnerLabel = document.getElementById("stateWinner");
  if (data.game_over) {
    winnerLabel.textContent = data.players[data.winner]?.display_name || data.winner || "Unknown";
  } else {
    winnerLabel.textContent = "-";
  }

  const notesEl = document.getElementById("playerNotes");
  const notesLines = [];
  if (state.channel.type === "dm") {
    const pid = state.channel.playerId;
    const name = data.players[pid]?.display_name || pid;
    const note = data.private_notes?.[pid] || "";
    notesLines.push(`${name}:\n${note || "(no notes)"}`);
  } else {
    for (const pid of Object.keys(data.players || {})) {
      const name = data.players[pid]?.display_name || pid;
      const note = data.private_notes?.[pid] || "";
      notesLines.push(`${name}:\n${note || "(no notes)"}`);
    }
  }
  notesEl.textContent = notesLines.join("\n\n");

  const biosEl = document.getElementById("playerBios");
  biosEl.innerHTML = "";
  const bios = [];
  if (state.channel.type === "dm") {
    const pid = state.channel.playerId;
    const player = data.players[pid];
    if (player?.bio) {
      bios.push({ pid, player });
    }
  } else {
    for (const pid of Object.keys(data.players || {})) {
      const player = data.players[pid];
      if (player?.bio) {
        bios.push({ pid, player });
      }
    }
  }
  if (!bios.length) {
    biosEl.textContent = "(no bios)";
  } else {
    for (const entry of bios) {
      const card = document.createElement("div");
      card.className = "bio-card";

      const avatar = document.createElement("img");
      avatar.className = "bio-avatar";
      avatar.src = getAvatarSrc(entry.pid);
      avatar.alt = entry.player.display_name || entry.pid;

      const text = document.createElement("pre");
      text.textContent = formatBio(entry.player.display_name || entry.pid, entry.player.bio);

      card.appendChild(avatar);
      card.appendChild(text);
      biosEl.appendChild(card);
    }
  }

  const rawEl = document.getElementById("rawOutputs");
  const days = data.days || [];
  const last = days[days.length - 1];
  const raw = [];
  if (last) {
    for (const event of last.events || []) {
      if (event.channel === "agent_raw") {
        raw.push(`${event.from}:\n${event.content}`);
      }
    }
  }
  rawEl.textContent = raw.join("\n\n") || "(none)";
}

function formatBio(label, bio) {
  const traits = (bio.personality_traits || []).join(", ");
  const interests = (bio.interests || []).join(", ");
  const funFacts = (bio.fun_facts || []).join(" | ");
  return [
    `${label}`,
    `Career: ${bio.career || "-"}`,
    `Personality Traits: ${traits || "-"}`,
    `Interests: ${interests || "-"}`,
    `Family: ${bio.family || "-"}`,
    `Fun Facts: ${funFacts || "-"}`,
  ].join("\n");
}

function getAvatarSrc(pid) {
  const num = (pid || "").replace(/[^0-9]/g, "");
  if (!num) return "";
  return `/img/${num}.png`;
}

function resolvePidFromName(data, name) {
  const players = data.players || {};
  for (const pid of Object.keys(players)) {
    const player = players[pid];
    if (player?.display_name === name || pid === name) {
      return pid;
    }
  }
  return null;
}

function renderMarkdown(text) {
  const escaped = escapeHtml(text);
  let out = escaped;
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, "$1<em>$2</em>");
  out = out.replace(/\n/g, "<br>");
  return out;
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderControls(data) {
  return;
}

function renderAll() {
  if (!state.data) return;
  renderChannels(state.data);
  renderRoundTabs(state.data);
  renderFeed(state.data);
  renderState(state.data);
  renderControls(state.data);
}

async function refresh() {
  state.data = await apiGet("/api/state");
  try {
    const auto = await apiGet("/api/auto_status");
    state.auto = Boolean(auto.running);
    if (state.auto && !state.autoPoll) {
      state.autoPoll = startPolling();
    }
    if (!state.auto && state.autoPoll) {
      state.autoPoll.stop();
      state.autoPoll = null;
    }
  } catch (err) {
    console.error(err);
  }
  renderAll();
}

function bindActions() {
  document.getElementById("initBtn").addEventListener("click", async () => {
    state.data = await apiPost("/api/init", { force_regen_bios: false });
    renderAll();
  });

  document.getElementById("regenBtn").addEventListener("click", async () => {
    state.data = await apiPost("/api/init", { force_regen_bios: true });
    renderAll();
  });

  document.getElementById("runRoundBtn").addEventListener("click", async () => {
    const btn = document.getElementById("runRoundBtn");
    btn.disabled = true;
    console.log("[ui] advance round");
    const poll = startPolling();
    try {
      const res = await apiPost("/api/run_round", {});
      state.data = res;
    } finally {
      poll.stop();
      btn.disabled = false;
      renderAll();
    }
  });

  document.getElementById("startVoteBtn").addEventListener("click", async () => {
    const btn = document.getElementById("startVoteBtn");
    btn.disabled = true;
    console.log("[ui] start vote");
    state.data = await apiPost("/api/start_vote", {});
    btn.disabled = false;
    renderAll();
  });

  document.getElementById("autoBtn").addEventListener("click", async () => {
    state.auto = !state.auto;
    updateAutoButton();
    if (state.auto) {
      await apiPost("/api/auto_start", {});
      if (!state.autoPoll) {
        state.autoPoll = startPolling();
      }
    } else {
      await apiPost("/api/auto_stop", {});
      if (state.autoPoll) {
        state.autoPoll.stop();
        state.autoPoll = null;
      }
    }
  });

  document.getElementById("moneyToggle").addEventListener("change", () => {
    renderState(state.data);
  });
}

bindActions();
refresh();

function startPolling() {
  let active = true;
  const interval = setInterval(async () => {
    if (!active) return;
    try {
      const data = await apiGet("/api/state");
      state.data = data;
      renderAll();
    } catch (err) {
      console.error(err);
    }
  }, 1500);
  return {
    stop() {
      active = false;
      clearInterval(interval);
    },
  };
}

function updateAutoButton() {
  const btn = document.getElementById("autoBtn");
  btn.textContent = state.auto ? "Auto: On" : "Auto";
}
