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

  let busy = false;
  let pendingApproval = null;
  let activityEl = null;
  function autoApproveEnabled() {
    return (
      window.__MINIAI_AUTO_APPROVE === true ||
      /(?:\?|&)auto_approve=1(?:&|$)/.test(location.search) ||
      location.hash === "#auto_approve"
    );
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
      // inline code first
      t = t.replace(/`([^`]+)`/g, function (_, code) {
        return "<code>" + code + "</code>";
      });
      t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      t = t.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
      // links — only http(s); javascript: and others become plain text
      t = t.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, label, url) {
        const u = url.trim();
        if (/^https?:\/\//i.test(u)) {
          return (
            '<a class="md-link" href="' +
            escapeHtml(u) +
            '" target="_blank" rel="noopener noreferrer">' +
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
      if (line.trim() === "") {
        continue;
      }
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
    const wrap = document.createElement("div");
    wrap.className = "msg-ai";
    wrap.innerHTML =
      '<div class="avatar">M</div><div class="body"></div>';
    thread.appendChild(wrap);
    return wrap.querySelector(".body");
  }

  function setTainted(on) {
    if (on) chipTaint.removeAttribute("hidden");
    else chipTaint.setAttribute("hidden", "");
  }

  function showActivity(steps, waiting) {
    const body = ensureAiBody();
    const details = document.createElement("details");
    details.className = "activity";
    if (waiting) details.open = true;
    const summary = document.createElement("summary");
    const n = steps.length;
    const label = waiting
      ? "Waiting for your approval"
      : "Worked · " + n + " step" + (n === 1 ? "" : "s");
    summary.innerHTML =
      (waiting
        ? '<span class="spinner"></span>'
        : '<span class="ic ok-ic">✓</span>') +
      escapeHtml(label) +
      '<svg class="chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>';
    details.appendChild(summary);
    if (steps.length) {
      const ul = document.createElement("ul");
      ul.className = "steps";
      steps.forEach(function (s) {
        const li = document.createElement("li");
        li.className = "step";
        li.innerHTML =
          '<span class="ic">✓</span>' +
          escapeHtml(s.name || "tool") +
          '<span class="t">' +
          escapeHtml(s.t || "") +
          "</span>";
        ul.appendChild(li);
      });
      details.appendChild(ul);
    }
    body.appendChild(details);
    activityEl = details;
    scrollBottom();
    return body;
  }

  function showAnswer(markdown, sources) {
    let body = activityEl
      ? activityEl.parentElement
      : ensureAiBody();
    if (activityEl && activityEl.open) activityEl.open = false;
    const html = renderMarkdown(markdown);
    const holder = document.createElement("div");
    holder.innerHTML = html;
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
      : showActivity([], true);
    const typed = !!req.typed;
    const card = document.createElement("div");
    card.className = "approval" + (typed ? " typed" : "");
    const notice = req.banner
      ? '<div class="notice"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex:none;margin-top:1px"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>' +
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
      clearApproval();
      const a = api();
      if (a && a.approval_reply) a.approval_reply(value);
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

  async function send() {
    const text = composer.value.trim();
    if (!text || busy) return;
    busy = true;
    btnSend.disabled = true;
    composer.value = "";
    addUser(text);
    if (chatTitle.textContent === "New chat") {
      chatTitle.textContent =
        text.length > 48 ? text.slice(0, 48) + "…" : text;
    }
    showActivity([], false);
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

  // Called from Python via evaluate_js
  window.miniai = {
    on_status: function (st) {
      if (st.model) modelStatus.textContent = st.model;
      if (st.runner) chipRunner.textContent = st.runner;
      if (typeof st.tainted === "boolean") setTainted(st.tainted);
      if (st.memory_pct != null) {
        memMeter.style.width = Math.max(0, Math.min(100, st.memory_pct)) + "%";
      }
      if (st.memory_label) memLabel.textContent = st.memory_label;
    },
    on_tools: function (steps) {
      if (activityEl) activityEl.remove();
      showActivity(steps || [], false);
    },
    on_approval: function (req) {
      if (activityEl) {
        activityEl.open = true;
        const sum = activityEl.querySelector("summary");
        if (sum)
          sum.innerHTML =
            '<span class="spinner"></span>Waiting for your approval<svg class="chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>';
      }
      showApprovalCard(req || {});
    },
    on_answer: function (payload) {
      showAnswer(
        (payload && payload.text) || "",
        (payload && payload.sources) || []
      );
      if (typeof payload.tainted === "boolean") setTainted(payload.tainted);
      busy = false;
      btnSend.disabled = false;
      composer.focus();
    },
    on_error: function (msg) {
      showAnswer(String(msg || "Error"));
      busy = false;
      btnSend.disabled = false;
    },
    /** Test hook: render markdown into a throwaway node and return outerHTML. */
    _test_render: function (text) {
      const d = document.createElement("div");
      d.innerHTML = renderMarkdown(text);
      return d.innerHTML;
    },
  };

  btnSend.addEventListener("click", send);
  btnStop.addEventListener("click", function () {
    /* visual only in 11a */
  });
  btnNew.addEventListener("click", function () {
    /* visual only in 11a */
  });
  composer.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  let lastApprovalKey = "";
  async function pollApprovals() {
    const a = api();
    if (!a || !a.poll_approval) return;
    try {
      const req = await a.poll_approval();
      if (!req) return;
      const key = JSON.stringify(req);
      if (key === lastApprovalKey && pendingApproval) return;
      lastApprovalKey = key;
      window.miniai.on_approval(req);
    } catch (e) {
      /* bridge not ready yet */
    }
  }

  // Poll even before pywebviewready — Edge/file:// can delay that event.
  setInterval(pollApprovals, 250);

  window.addEventListener("pywebviewready", function () {
    const a = api();
    if (a && a.ready) a.ready();
  });
})();
