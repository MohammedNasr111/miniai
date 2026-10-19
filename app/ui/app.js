/* MiniAI app UI — talks to Python only via pywebview js_api (no HTTP). */
(function () {
  "use strict";

  const thread = document.getElementById("thread");
  const scroll = document.getElementById("scroll");
  const composer = document.getElementById("composer");
  const btnSend = document.getElementById("btn-send");
  const btnStop = document.getElementById("btn-stop");
  const btnNew = document.getElementById("btn-new-chat");
  const chipTaint = document.getElementById("chip-taint");
  const chipRunner = document.getElementById("chip-runner");
  const modelStatus = document.getElementById("model-status");
  const memMeter = document.getElementById("mem-meter");
  const memLabel = document.getElementById("mem-label");
  const chatTitle = document.getElementById("chat-title");
  const historyList = document.getElementById("history-list");
  const ctxMenu = document.getElementById("ctx-menu");
  const ctxDelete = document.getElementById("ctx-delete");

  let busy = false;
  let readonly = false;
  let pendingApproval = null;
  let activityEl = null;
  let ctxChatId = null;
  let activeChatId = null;

  function autoApproveEnabled() {
    return window.__MINIAI_AUTO_APPROVE === true;
  }

  function api() {
    return window.pywebview && window.pywebview.api;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /** Safe markdown subset: bold, italics, inline code, lists, links. Escape everything else. */
  function renderMarkdown(src) {
    const text = String(src || "");
    const lines = text.split(/\r?\n/);
    const out = [];
    let inList = false;

    function inline(s) {
      let t = escapeHtml(s);
      t = t.replace(/`([^`]+)`/g, function (_, code) {
        return "<code>" + code + "</code>";
      });
      t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      t = t.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
      t = t.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, label, url) {
        const u = url.trim();
        if (/^https?:\/\//i.test(u)) {
          return (
            '<a class="md-link" href="' +
            escapeHtml(u) +
            '" rel="noopener noreferrer">' +
            label +
            "</a>"
          );
        }
        return label + " (" + escapeHtml(u) + ")";
      });
      return t;
    }

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const m = /^(?:[-*]|\d+\.)\s+(.*)$/.exec(line);
      if (m) {
        if (!inList) {
          out.push("<ul>");
          inList = true;
        }
        out.push("<li>" + inline(m[1]) + "</li>");
        continue;
      }
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      if (line.trim() === "") continue;
      out.push("<p>" + inline(line) + "</p>");
    }
    if (inList) out.push("</ul>");
    return out.join("") || "<p></p>";
  }

  function scrollBottom() {
    scroll.scrollTop = scroll.scrollHeight;
  }

  function addUser(text) {
    const el = document.createElement("div");
    el.className = "msg-user";
    el.textContent = text;
    thread.appendChild(el);
    scrollBottom();
  }

  function ensureAiBody() {
    if (activityEl && activityEl.parentElement) {
      return activityEl.parentElement;
    }
    const wrap = document.createElement("div");
    wrap.className = "msg-ai";
    wrap.innerHTML = '<div class="avatar">M</div><div class="body"></div>';
    thread.appendChild(wrap);
    return wrap.querySelector(".body");
  }

  function setTainted(on) {
    if (on) chipTaint.removeAttribute("hidden");
    else chipTaint.setAttribute("hidden", "");
  }

  function summaryLabel(payload) {
    if (payload.waiting) return "Waiting for your approval";
    const n = (payload.steps || []).length;
    const total = payload.total || "";
    if (payload.running) {
      if (n === 0) return "Working…";
      return "Working · " + n + " step" + (n === 1 ? "" : "s");
    }
    if (total) {
      return (
        "Worked for " +
        total +
        " · " +
        n +
        " step" +
        (n === 1 ? "" : "s")
      );
    }
    return "Worked · " + n + " step" + (n === 1 ? "" : "s");
  }

  function renderActivity(payload) {
    const body = ensureAiBody();
    let details = activityEl;
    if (!details || !details.isConnected) {
      details = document.createElement("details");
      details.className = "activity";
      body.insertBefore(details, body.firstChild);
      activityEl = details;
    }
    details.open = !!(payload.waiting || payload.running);
    const steps = payload.steps || [];
    let ul = details.querySelector("ul.steps");
    if (!ul) {
      details.innerHTML = "";
      const summary = document.createElement("summary");
      details.appendChild(summary);
      ul = document.createElement("ul");
      ul.className = "steps";
      details.appendChild(ul);
    }
    const summary = details.querySelector("summary");
    const spinning = !!(payload.waiting || payload.running);
    summary.innerHTML =
      (spinning
        ? '<span class="spinner"></span>'
        : '<span class="ic ok-ic">✓</span>') +
      escapeHtml(summaryLabel(payload)) +
      '<svg class="chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>';
    ul.innerHTML = "";
    steps.forEach(function (s) {
      const li = document.createElement("li");
      li.className = "step";
      const ic = s.running
        ? '<span class="spinner"></span>'
        : '<span class="ic">✓</span>';
      li.innerHTML =
        ic +
        escapeHtml(s.name || "tool") +
        '<span class="t">' +
        escapeHtml(s.t || "") +
        "</span>";
      ul.appendChild(li);
    });
    scrollBottom();
    return body;
  }

  function showAnswer(markdown, sources, stepsPayload) {
    if (stepsPayload) {
      renderActivity({
        steps: stepsPayload.steps || [],
        total: stepsPayload.total || "",
        waiting: false,
        running: false,
      });
    }
    const body = ensureAiBody();
    if (activityEl && activityEl.open) activityEl.open = false;
    const holder = document.createElement("div");
    holder.innerHTML = renderMarkdown(markdown);
    body.appendChild(holder);
    if (sources && sources.length) {
      const box = document.createElement("div");
      box.className = "sources";
      sources.forEach(function (s, i) {
        const a = document.createElement("a");
        a.className = "source";
        const href = s.url || "#";
        if (/^https?:\/\//i.test(href)) a.href = href;
        else a.href = "#";
        a.innerHTML =
          '<span class="n">' +
          (i + 1) +
          "</span>" +
          escapeHtml(s.label || href);
        box.appendChild(a);
      });
      body.appendChild(box);
    }
    scrollBottom();
  }

  function showSystemNote(text) {
    const el = document.createElement("div");
    el.className = "sys-note";
    el.textContent = text;
    thread.appendChild(el);
    scrollBottom();
  }

  function clearApproval() {
    if (pendingApproval && pendingApproval.root) {
      pendingApproval.root.remove();
    }
    pendingApproval = null;
  }

  function showApprovalCard(req) {
    clearApproval();
    const body = activityEl
      ? activityEl.parentElement
      : renderActivity({ steps: [], waiting: true, running: false, total: "" });
    if (activityEl) {
      activityEl.open = true;
      const sum = activityEl.querySelector("summary");
      if (sum) {
        sum.innerHTML =
          '<span class="spinner"></span>Waiting for your approval<svg class="chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>';
      }
    }
    const typed = !!req.typed;
    const card = document.createElement("div");
    card.className = "approval" + (typed ? " typed" : "");
    card.dataset.nonce = req.id || "";
    const notice = req.banner
      ? '<div class="notice"><svg class="notice-ic" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>' +
        escapeHtml(req.banner.replace(/\n/g, " ").trim()) +
        "</div>"
      : "";
    card.innerHTML =
      '<div class="head">' +
      '<div class="shield"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3Z"/></svg></div>' +
      "<b>" +
      escapeHtml(req.title || (typed ? "Confirm action" : "Allow action")) +
      '</b><span class="badge">' +
      escapeHtml(req.action || "") +
      "</span></div>" +
      '<div class="content">' +
      '<div class="pre">' +
      escapeHtml(req.description || "") +
      "</div>" +
      notice +
      "</div>" +
      '<div class="actions"></div>';

    const actions = card.querySelector(".actions");
    let typedInput = null;
    if (typed) {
      typedInput = document.createElement("input");
      typedInput.className = "typed-input";
      typedInput.placeholder = "Type " + (req.action || "") + " to approve";
      typedInput.autocomplete = "off";
      typedInput.spellcheck = false;
      actions.appendChild(typedInput);
    }
    const deny = document.createElement("button");
    deny.className = "btn";
    deny.type = "button";
    deny.textContent = "Deny";
    const approve = document.createElement("button");
    approve.className = "btn primary";
    approve.type = "button";
    approve.textContent = "Approve";
    if (typed) approve.disabled = true;
    actions.appendChild(deny);
    actions.appendChild(approve);

    function typedOk() {
      if (!typed || !typedInput) return true;
      const v = typedInput.value.trim();
      if (req.mode === "app_read") return v === "session" || v === "always";
      return v === req.action;
    }

    if (typed && typedInput) {
      typedInput.addEventListener("input", function () {
        approve.disabled = !typedOk();
      });
      if (req.mode === "app_read") {
        typedInput.placeholder = "Type session or always";
      }
    }

    function resolve(value) {
      const nonce = req.id || card.dataset.nonce || "";
      clearApproval();
      const a = api();
      if (a && a.approval_reply) a.approval_reply(nonce, value);
    }

    deny.addEventListener("click", function () {
      resolve(typed ? "" : "no");
    });
    approve.addEventListener("click", function () {
      if (typed) {
        if (!typedOk()) return;
        resolve(typedInput.value.trim());
      } else {
        resolve("yes");
      }
    });

    body.appendChild(card);
    pendingApproval = { root: card, req: req };
    scrollBottom();
    if (typedInput) typedInput.focus();
    if (autoApproveEnabled()) {
      setTimeout(function () {
        if (typed && typedInput) {
          typedInput.value =
            req.mode === "app_read" ? "session" : req.action || "";
          typedInput.dispatchEvent(new Event("input"));
        }
        if (!approve.disabled) approve.click();
      }, 80);
    }
  }

  function renderHistory(groups) {
    historyList.innerHTML = "";
    (groups || []).forEach(function (g) {
      const lab = document.createElement("div");
      lab.className = "section-label";
      lab.textContent = g.section || "";
      historyList.appendChild(lab);
      (g.items || []).forEach(function (it) {
        const btn = document.createElement("button");
        btn.className =
          "chat-item" + (it.id === activeChatId ? " active" : "");
        btn.type = "button";
        btn.textContent = it.title || "Chat";
        btn.dataset.id = it.id;
        btn.addEventListener("click", function () {
          openSaved(it.id);
        });
        btn.addEventListener("contextmenu", function (e) {
          e.preventDefault();
          ctxChatId = it.id;
          ctxMenu.removeAttribute("hidden");
          ctxMenu.style.left = e.clientX + "px";
          ctxMenu.style.top = e.clientY + "px";
        });
        historyList.appendChild(btn);
      });
    });
  }

  async function openSaved(id) {
    const a = api();
    if (!a || !a.open_chat) return;
    const res = await a.open_chat(id);
    if (!res || !res.ok) return;
    readonly = true;
    activeChatId = id;
    busy = false;
    btnSend.disabled = false;
    activityEl = null;
    clearApproval();
    thread.innerHTML = "";
    const chat = res.chat || {};
    chatTitle.textContent = chat.title || "Chat";
    (chat.messages || []).forEach(function (m) {
      if (m.role === "user") addUser(m.text || "");
      else if (m.role === "assistant") {
        activityEl = null;
        showAnswer(m.text || "", m.sources || []);
        activityEl = null;
      }
    });
    showSystemNote(res.note || "Continue in a new chat");
    renderHistory(await a.list_chats());
  }

  async function doNewChat() {
    const a = api();
    if (a && a.new_chat) await a.new_chat();
    readonly = false;
    activeChatId = null;
    busy = false;
    btnSend.disabled = false;
    activityEl = null;
    clearApproval();
    thread.innerHTML = "";
    chatTitle.textContent = "New chat";
    setTainted(false);
    composer.focus();
    if (a && a.list_chats) renderHistory(await a.list_chats());
  }

  async function stop() {
    const a = api();
    if (a && a.stop_turn) await a.stop_turn();
  }

  async function send() {
    let text = composer.value.trim();
    if (!text || busy) return;
    if (readonly) {
      await doNewChat();
    }
    busy = true;
    btnSend.disabled = true;
    composer.value = "";
    addUser(text);
    if (chatTitle.textContent === "New chat") {
      chatTitle.textContent =
        text.length > 40 ? text.slice(0, 39) + "…" : text;
    }
    activityEl = null;
    renderActivity({ steps: [], waiting: false, running: true, total: "0s" });
    try {
      const a = api();
      if (!a) throw new Error("Python bridge not ready");
      await a.send_message(text);
    } catch (e) {
      showAnswer("Error: " + (e && e.message ? e.message : String(e)));
      busy = false;
      btnSend.disabled = false;
    }
  }

  window.miniai = {
    on_status: function (st) {
      if (st.model) modelStatus.textContent = st.model;
      if (st.runner) chipRunner.textContent = st.runner;
      if (typeof st.tainted === "boolean") setTainted(st.tainted);
      if (st.memory_pct != null) {
        memMeter.style.width =
          Math.max(0, Math.min(100, st.memory_pct)) + "%";
      }
      memMeter.classList.remove("ok", "warn", "danger");
      memMeter.classList.add(st.memory_level || "ok");
      if (st.memory_label) memLabel.textContent = st.memory_label;
    },
    on_activity: function (payload) {
      renderActivity(payload || {});
    },
    on_approval: function (req) {
      showApprovalCard(req || {});
    },
    on_answer: function (payload) {
      showAnswer(
        (payload && payload.text) || "",
        (payload && payload.sources) || [],
        {
          steps: (payload && payload.steps) || [],
          total: (payload && payload.total) || "",
        }
      );
      if (typeof payload.tainted === "boolean") setTainted(payload.tainted);
      busy = false;
      btnSend.disabled = false;
      composer.focus();
    },
    on_cancelled: function (payload) {
      clearApproval();
      showSystemNote((payload && payload.note) || "Cancelled.");
      if (activityEl) {
        renderActivity({
          steps: [],
          waiting: false,
          running: false,
          total: "",
        });
      }
      busy = false;
      btnSend.disabled = false;
      composer.focus();
    },
    on_error: function (msg) {
      clearApproval();
      renderActivity({
        steps: [],
        waiting: false,
        running: false,
        total: "",
      });
      showSystemNote(String(msg || "Error"));
      busy = false;
      btnSend.disabled = false;
      composer.focus();
    },
    on_history: function (groups) {
      renderHistory(groups || []);
    },
    _test_render: function (text) {
      const d = document.createElement("div");
      d.innerHTML = renderMarkdown(text);
      return d.innerHTML;
    },
  };

  // Navigation lock: never follow links inside the webview.
  document.addEventListener(
    "click",
    function (e) {
      const a = e.target && e.target.closest ? e.target.closest("a") : null;
      if (!a) return;
      const href = a.getAttribute("href") || "";
      if (!href || href === "#") {
        e.preventDefault();
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      const bridge = api();
      if (bridge && bridge.open_external) bridge.open_external(href);
    },
    true
  );

  btnSend.addEventListener("click", send);
  btnStop.addEventListener("click", stop);
  btnNew.addEventListener("click", doNewChat);
  composer.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && (e.key === "n" || e.key === "N")) {
      e.preventDefault();
      doNewChat();
    }
    if (e.key === "Escape") {
      e.preventDefault();
      stop();
      ctxMenu.setAttribute("hidden", "");
    }
  });
  ctxDelete.addEventListener("click", async function () {
    ctxMenu.setAttribute("hidden", "");
    if (!ctxChatId) return;
    const a = api();
    if (a && a.delete_chat) {
      const res = await a.delete_chat(ctxChatId);
      if (ctxChatId === activeChatId) await doNewChat();
      else if (res && res.history) renderHistory(res.history);
    }
    ctxChatId = null;
  });
  document.addEventListener("click", function () {
    ctxMenu.setAttribute("hidden", "");
  });

  let lastApprovalKey = "";
  async function pollApprovals() {
    const a = api();
    if (!a || !a.poll_approval) return;
    try {
      const req = await a.poll_approval();
      if (!req) return;
      const key = req.id || JSON.stringify(req);
      if (key === lastApprovalKey && pendingApproval) return;
      lastApprovalKey = key;
      window.miniai.on_approval(req);
    } catch (e) {
      /* bridge not ready */
    }
  }
  setInterval(pollApprovals, 250);

  window.addEventListener("pywebviewready", function () {
    const a = api();
    if (a && a.ready) a.ready();
  });
})();
