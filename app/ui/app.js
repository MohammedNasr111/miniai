/* MiniAI v2 UI — run log + footprint. Bridge: pywebview js_api only. */
(function () {
  "use strict";

  const appEl = document.getElementById("app");
  const runsEl = document.getElementById("runs");
  const scroll = document.getElementById("scroll");
  const composer = document.getElementById("composer");
  const composerForm = document.getElementById("composer-form");
  const btnSend = document.getElementById("btn-send");
  const btnNew = document.getElementById("btn-new-chat");
  const chipTaint = document.getElementById("chip-taint");
  const modelStatus = document.getElementById("model-status");
  const modelLamp = document.getElementById("model-lamp");
  const memMeter = document.getElementById("mem-meter");
  const memLabel = document.getElementById("mem-label");
  const tokSpeed = document.getElementById("tok-speed");
  const selfcheckLabel = document.getElementById("selfcheck-label");
  const chatTitle = document.getElementById("chat-title");
  const historyList = document.getElementById("history-list");
  const ctxMenu = document.getElementById("ctx-menu");
  const ctxDelete = document.getElementById("ctx-delete");
  const openRail = document.getElementById("open-rail");
  const openFoot = document.getElementById("open-foot");
  const scrim = document.getElementById("scrim");
  const jumpLatest = document.getElementById("jump-latest");
  const palette = document.getElementById("palette");
  const paletteInput = document.getElementById("palette-input");
  const paletteList = document.getElementById("palette-list");

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let busy = false;
  let readonly = false;
  let pendingApproval = null;
  let activeChatId = null;
  let ctxChatId = null;
  let currentRun = null;
  let pinBottom = true;
  let lastAnswerText = "";
  let streamPending = "";
  let streamLastPaint = 0;
  let streamTimer = null;
  let streamCaret = null;
  const STREAM_MIN_MS = 50;
  let paletteIndex = 0;
  let paletteItems = [];
  let chatIndex = [];

  const EXAMPLES = [
    {
      text: "Move the installer files in my Downloads folder into a folder called Installers.",
      tag: "Files",
    },
    {
      text: "What changed in the latest Windows 11 update?",
      tag: "Web",
    },
    {
      text: "Write a Python function that counts words in a string, with tests.",
      tag: "Code",
    },
  ];

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

  function nowHm() {
    const d = new Date();
    return (
      String(d.getHours()).padStart(2, "0") +
      ":" +
      String(d.getMinutes()).padStart(2, "0")
    );
  }

  function renderMarkdown(src) {
    const text = String(src || "");
    const lines = text.split(/\r?\n/);
    const out = [];
    const stack = [];

    function inline(s) {
      let t = escapeHtml(s);
      t = t.replace(/`([^`]+)`/g, function (_, code) {
        return "<code class=\"path\">" + code + "</code>";
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

    function closeTo(indent) {
      while (stack.length && stack[stack.length - 1].indent > indent) {
        const frame = stack.pop();
        if (frame.openLi) out.push("</li>");
        out.push("</" + frame.type + ">");
      }
    }

    function closeAll() {
      while (stack.length) {
        const frame = stack.pop();
        if (frame.openLi) out.push("</li>");
        out.push("</" + frame.type + ">");
      }
    }

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const indentMatch = /^([ \t]*)([-*]|\d+\.)\s+(.*)$/.exec(line);
      if (indentMatch) {
        const rawIndent = indentMatch[1].replace(/\t/g, "  ");
        const level = Math.floor(rawIndent.length / 2);
        const marker = indentMatch[2];
        const body = indentMatch[3];
        const listType = /^\d+\.$/.test(marker) ? "ol" : "ul";
        closeTo(level);
        let top = stack[stack.length - 1];
        if (!top || top.indent < level) {
          out.push("<" + listType + ">");
          stack.push({ type: listType, indent: level, openLi: false });
          top = stack[stack.length - 1];
        } else if (top.indent === level && top.type !== listType) {
          if (top.openLi) out.push("</li>");
          out.push("</" + top.type + ">");
          stack.pop();
          out.push("<" + listType + ">");
          stack.push({ type: listType, indent: level, openLi: false });
          top = stack[stack.length - 1];
        } else if (top.indent === level && top.openLi) {
          out.push("</li>");
          top.openLi = false;
        }
        out.push("<li>" + inline(body));
        stack[stack.length - 1].openLi = true;
        continue;
      }
      if (line.trim() === "") {
        closeAll();
        continue;
      }
      closeAll();
      out.push("<p>" + inline(line) + "</p>");
    }
    closeAll();
    return out.join("") || "<p></p>";
  }

  function setTurnControls(running) {
    busy = !!running;
    if (!btnSend) return;
    if (busy) {
      btnSend.disabled = false;
      btnSend.classList.add("is-stop");
      btnSend.title = "Stop";
      btnSend.setAttribute("aria-label", "Stop");
    } else {
      btnSend.disabled = false;
      btnSend.classList.remove("is-stop");
      btnSend.title = "Send";
      btnSend.setAttribute("aria-label", "Send");
    }
    void btnSend.offsetWidth;
  }

  function maybeScrollBottom() {
    if (pinBottom) {
      scroll.scrollTop = scroll.scrollHeight;
      jumpLatest.hidden = true;
    } else {
      jumpLatest.hidden = false;
    }
  }

  function updatePinFromScroll() {
    const dist = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight;
    pinBottom = dist < 80;
    jumpLatest.hidden = pinBottom;
  }

  scroll.addEventListener("scroll", updatePinFromScroll, { passive: true });
  jumpLatest.addEventListener("click", function () {
    pinBottom = true;
    maybeScrollBottom();
  });

  function clearRuns() {
    runsEl.innerHTML = "";
    currentRun = null;
    pendingApproval = null;
  }

  function showEmptyState() {
    clearRuns();
    const box = document.createElement("div");
    box.className = "empty";
    box.innerHTML = "<h2>Try one of these</h2>";
    const ex = document.createElement("div");
    ex.className = "examples";
    EXAMPLES.forEach(function (e) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "example";
      b.innerHTML =
        escapeHtml(e.text) + "<small>" + escapeHtml(e.tag) + "</small>";
      b.addEventListener("click", function () {
        composer.value = e.text;
        composer.focus();
        autoSize();
        sendMessage();
      });
      ex.appendChild(b);
    });
    box.appendChild(ex);
    runsEl.appendChild(box);
  }

  function startRun(userText) {
    const empty = runsEl.querySelector(".empty");
    if (empty) empty.remove();
    const art = document.createElement("article");
    art.className = "run";
    art.setAttribute("aria-label", "Run");
    const ask = document.createElement("div");
    ask.className = "ask";
    const p = document.createElement("p");
    p.textContent = userText;
    ask.appendChild(p);
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML =
      "<span><b>" +
      escapeHtml(nowHm()) +
      "</b></span><span class=\"meta-status\">Working</span><span class=\"meta-steps\"><b>0</b> steps</span><span class=\"meta-left\"><b>Nothing</b> left this PC</span>";
    ask.appendChild(meta);
    art.appendChild(ask);
    const trace = document.createElement("ol");
    trace.className = "trace";
    art.appendChild(trace);
    const answer = document.createElement("div");
    answer.className = "answer";
    answer.hidden = true;
    art.appendChild(answer);
    runsEl.appendChild(art);
    currentRun = {
      root: art,
      trace: trace,
      answer: answer,
      meta: meta,
      stepEls: [],
      leftCount: 0,
      t0: Date.now(),
    };
    maybeScrollBottom();
    return currentRun;
  }

  function updateRunMeta(run, opts) {
    if (!run || !run.meta) return;
    const st = run.meta.querySelector(".meta-status");
    const steps = run.meta.querySelector(".meta-steps");
    const left = run.meta.querySelector(".meta-left");
    if (opts.status != null && st) st.innerHTML = opts.status;
    if (steps) {
      const n = opts.steps != null ? opts.steps : run.stepEls.length;
      steps.innerHTML = "<b>" + n + "</b> step" + (n === 1 ? "" : "s");
    }
    if (left) {
      const n = opts.left != null ? opts.left : run.leftCount;
      if (n <= 0) {
        left.innerHTML = "<b>Nothing</b> left this PC";
      } else {
        left.innerHTML =
          "<b>" +
          n +
          " search" +
          (n === 1 ? "" : "es") +
          "</b> left this PC";
      }
    }
  }

  function appendStep(payload) {
    const run = currentRun;
    if (!run) return null;
    const kind = payload.k || payload.kind || "change";
    const li = document.createElement("li");
    li.className = "step" + (payload.running ? " live" : "");
    li.dataset.k = kind;
    li.innerHTML =
      '<span class="node"><i></i></span><span class="what"></span><span class="t"></span>';
    const what = li.querySelector(".what");
    what.appendChild(document.createTextNode(payload.name || "Working"));
    if (payload.detail) {
      const sm = document.createElement("small");
      sm.textContent = payload.detail;
      what.appendChild(sm);
    }
    li.querySelector(".t").textContent = payload.t || "";
    run.trace.appendChild(li);
    run.stepEls.push(li);
    if (kind === "out") {
      run.leftCount += 1;
      updateRunMeta(run, { left: run.leftCount });
    }
    updateRunMeta(run, { steps: run.stepEls.length });
    maybeScrollBottom();
    return li;
  }

  function ellipsisPath(path, maxLen) {
    maxLen = maxLen || 48;
    var s = String(path || "").replace(/\//g, "\\");
    if (!s || s.length <= maxLen) return s;
    var head = "";
    var tail = s;
    if (s.length >= 2 && s.charAt(1) === ":") {
      head = s.slice(0, 3);
      tail = s.slice(3);
    } else if (s.indexOf("\\\\") === 0) {
      var parts = s.split("\\");
      if (parts.length >= 4) {
        head = "\\\\" + parts[2] + "\\" + parts[3] + "\\";
        tail = parts.slice(4).join("\\");
      } else {
        return s;
      }
    } else {
      var keep = Math.max(8, Math.floor(maxLen / 2) - 1);
      return s.slice(0, keep) + "…" + s.slice(-(maxLen - keep - 1));
    }
    if (!tail) return head.replace(/\\$/, "") || head;
    var budget = Math.max(8, maxLen - head.length - 1);
    if (tail.length <= budget) return head + tail;
    return head + "…" + tail.slice(-(budget - 1));
  }

  function syncSteps(payload) {
    const run = currentRun || startRun("(working)");
    const steps = payload.steps || [];
    // Keep tickets; re-insert each under its matching action node (never above).
    const tickets = Array.from(run.trace.querySelectorAll(":scope > .ticket"));
    tickets.forEach(function (t) {
      t._placed = false;
    });
    run.trace.innerHTML = "";
    run.stepEls = [];
    run.leftCount = 0;
    steps.forEach(function (s) {
      appendStep({
        k: s.k || s.kind || "change",
        name: s.name,
        detail: s.detail || "",
        t: s.t || "",
        running: !!s.running,
      });
      const tool = s.tool || "";
      if (tool) {
        tickets.forEach(function (t) {
          if (!t._placed && t.dataset.tool === tool) {
            run.trace.appendChild(t);
            t._placed = true;
          }
        });
      }
    });
    // Any ticket without a matching step goes after the steps (still below).
    tickets.forEach(function (t) {
      if (!t._placed) run.trace.appendChild(t);
    });
    if (payload.checking) {
      appendStep({
        k: "verify",
        name: "Checking the answer against sources",
        detail: "",
        t: "",
        running: true,
      });
    }
    updateRunMeta(run, {
      status: payload.waiting
        ? "Waiting for you"
        : payload.running
          ? "Working"
          : null,
    });
  }

  function clearStreamTimer() {
    if (streamTimer) {
      clearTimeout(streamTimer);
      streamTimer = null;
    }
  }

  function ensureAnswerStream() {
    const run = currentRun;
    if (!run) return null;
    run.answer.hidden = false;
    let p = run.answer.querySelector(".stream-md");
    if (!p) {
      p = document.createElement("div");
      p.className = "stream-md answer-md";
      run.answer.appendChild(p);
    }
    return p;
  }

  function paintStreamRaw(text) {
    const el = ensureAnswerStream();
    if (!el) return;
    // Light incremental markdown (escape-first via renderMarkdown); full
    // re-render happens on completion in showAnswer.
    el.innerHTML = renderMarkdown(text || "");
    if (!reduceMotion) {
      if (!streamCaret) {
        streamCaret = document.createElement("span");
        streamCaret.className = "caret";
      }
      el.appendChild(streamCaret);
    }
    maybeScrollBottom();
  }

  function flushStreamPaint() {
    streamLastPaint = Date.now();
    paintStreamRaw(streamPending);
    streamTimer = null;
  }

  function onStreamDelta(text) {
    streamPending = text || "";
    const now = Date.now();
    const elapsed = now - streamLastPaint;
    if (elapsed >= STREAM_MIN_MS) {
      clearStreamTimer();
      flushStreamPaint();
    } else if (!streamTimer) {
      streamTimer = setTimeout(flushStreamPaint, STREAM_MIN_MS - elapsed);
    }
  }

  function onStreamClear() {
    clearStreamTimer();
    streamPending = "";
    streamLastPaint = 0;
    streamCaret = null;
    if (currentRun) {
      const raw = currentRun.answer.querySelector(".stream-raw");
      if (raw) raw.remove();
    }
  }

  function showAnswer(markdown, sources, stepsPayload, checkInfo) {
    if (stepsPayload) {
      syncSteps({
        steps: stepsPayload.steps || [],
        total: stepsPayload.total || "",
        waiting: false,
        running: false,
      });
    }
    const run = currentRun;
    if (!run) return;
    clearStreamTimer();
    streamPending = "";
    streamCaret = null;
    run.answer.hidden = false;
    run.answer.innerHTML = "";
    const md = document.createElement("div");
    md.className = "answer-md";
    md.innerHTML = renderMarkdown(markdown || "");
    run.answer.appendChild(md);
    if (sources && sources.length) {
      const box = document.createElement("div");
      box.className = "sources";
      sources.forEach(function (s) {
        const a = document.createElement("a");
        a.className = "src";
        const href = s.url || "#";
        if (/^https?:\/\//i.test(href)) a.href = href;
        else a.href = "#";
        a.textContent = s.label || href;
        box.appendChild(a);
      });
      run.answer.appendChild(box);
    }
    if (checkInfo && checkInfo.fixed && !checkInfo.silent) {
      if (checkInfo.note) {
        const note = document.createElement("div");
        note.className = "note";
        note.textContent = checkInfo.note || "Corrected after checking";
        run.answer.appendChild(note);
      }
      appendStep({
        k: "verify",
        name: "Checked the claim against what actually happened",
        detail: checkInfo.note || "Corrected after checking",
        t: "",
        running: false,
      });
    }
    const elapsedMs = Date.now() - (run.t0 || Date.now());
    const secs = Math.max(1, Math.round(elapsedMs / 1000));
    updateRunMeta(run, {
      status: "Took <b>" + (secs < 60 ? secs + " s" : Math.floor(secs / 60) + " m " + (secs % 60) + " s") + "</b>",
      steps: run.stepEls.length,
    });
    lastAnswerText = markdown || "";
    maybeScrollBottom();
  }

  function showStoppedPartial(partial) {
    clearStreamTimer();
    const text = (partial || streamPending || "").trim();
    onStreamClear();
    if (!text || !currentRun) return;
    currentRun.answer.hidden = false;
    currentRun.answer.innerHTML =
      '<div class="answer-md">' +
      renderMarkdown(text + "\n\n(stopped)") +
      "</div>";
    updateRunMeta(currentRun, { status: "Stopped" });
    maybeScrollBottom();
  }

  function showSystemNote(text) {
    const el = document.createElement("div");
    el.className = "sys-note";
    el.textContent = text;
    runsEl.appendChild(el);
    maybeScrollBottom();
  }

  function clearApproval() {
    if (pendingApproval && pendingApproval.root) {
      // leave collapsed ticket in place if marked done
      if (!pendingApproval.root.classList.contains("done")) {
        pendingApproval.root.remove();
      }
    }
    pendingApproval = null;
  }

  function showApprovalCard(req) {
    const run = currentRun || startRun("…");
    const reqId = (req && req.id) || "";
    // Poll can re-deliver the same approval after the user already answered.
    // Never resurrect a live ticket for an answered nonce.
    if (reqId) {
      const answered = run.trace.querySelector(
        '.ticket.done[data-nonce="' + reqId.replace(/"/g, '\\"') + '"]'
      );
      if (answered) return;
      const liveSame = run.trace.querySelector(
        '.ticket:not(.done)[data-nonce="' + reqId.replace(/"/g, '\\"') + '"]'
      );
      if (liveSame) return;
    }
    // Remove prior pending ticket (live only)
    if (pendingApproval && pendingApproval.root && !pendingApproval.root.classList.contains("done")) {
      pendingApproval.root.remove();
    }
    const copy = req.ticket || {};
    const kind = copy.kind || (req.action === "delete_file" ? "danger" : "change");
    const li = document.createElement("li");
    li.className = "ticket" + (kind === "danger" ? " danger" : "");
    li.dataset.nonce = reqId;
    if (req.action) li.dataset.tool = req.action;

    const h4 = document.createElement("h4");
    h4.textContent = copy.heading || req.title || "Allow action";
    li.appendChild(h4);

    const rows = document.createElement("div");
    rows.className = "rows";
    const pathText = copy.paths || req.description || "";
    pathText.split("\n").forEach(function (line) {
      if (!line.trim()) return;
      const span = document.createElement("span");
      span.className = "path";
      span.textContent = ellipsisPath(line.trim(), 56);
      span.title = line.trim();
      rows.appendChild(span);
    });
    const cons = document.createElement("p");
    let consText = copy.consequence || "";
    if (req.banner && /web content|untrusted|type the action/i.test(req.banner)) {
      consText +=
        (consText ? " " : "") +
        "Because this chat has read web text, type the action name to approve.";
    }
    cons.textContent = consText;
    rows.appendChild(cons);
    li.appendChild(rows);

    const actions = document.createElement("div");
    actions.className = "actions";
    const typed = !!req.typed;
    let typedInput = null;
    if (typed) {
      const lab = document.createElement("label");
      lab.style.fontSize = "var(--s1)";
      lab.style.color = "var(--muted)";
      lab.textContent = "Type ";
      const act = document.createElement("span");
      act.className = "path";
      act.style.color = "var(--text)";
      act.textContent =
        req.mode === "app_read" ? "session or always" : req.action || "";
      lab.appendChild(act);
      actions.appendChild(lab);
      typedInput = document.createElement("input");
      typedInput.className = "typed";
      typedInput.autocomplete = "off";
      typedInput.spellcheck = false;
      typedInput.placeholder =
        req.mode === "app_read" ? "session" : req.action || "";
      actions.appendChild(typedInput);
    }
    const approve = document.createElement("button");
    approve.className = "btn primary";
    approve.type = "button";
    approve.textContent = copy.approve || "Allow";
    if (typed) approve.disabled = true;
    const deny = document.createElement("button");
    deny.className = "btn";
    deny.type = "button";
    deny.textContent = copy.deny || "Don't allow";
    actions.appendChild(approve);
    actions.appendChild(deny);
    li.appendChild(actions);

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
    }

    function settle(text) {
      // Replace in place: no live buttons may remain on an answered ticket.
      li.className = "ticket done";
      li.innerHTML = "";
      const h = document.createElement("h4");
      h.textContent = text;
      li.appendChild(h);
      const btns = li.querySelectorAll("button, input");
      btns.forEach(function (b) {
        b.disabled = true;
        b.remove();
      });
    }

    function resolve(value, approved) {
      const nonce = req.id || li.dataset.nonce || "";
      const hm = nowHm();
      // Collapse BEFORE notifying Python so a poll cannot re-show live buttons.
      if (approved) {
        settle((copy.collapsed_ok || "You approved") + ", " + hm);
      } else {
        settle((copy.collapsed_no || "You denied the action") + ", " + hm);
      }
      pendingApproval = { root: li, settledId: nonce };
      const a = api();
      if (a && a.approval_reply) a.approval_reply(nonce, value);
    }

    deny.addEventListener("click", function () {
      resolve(typed ? "" : "no", false);
    });
    approve.addEventListener("click", function () {
      if (typed) {
        if (!typedOk()) return;
        resolve(typedInput.value.trim(), true);
      } else {
        resolve("yes", true);
      }
    });

    run.trace.appendChild(li);
    pendingApproval = { root: li, req: req };
    updateRunMeta(run, { status: "Waiting for you" });
    maybeScrollBottom();
    if (typedInput) typedInput.focus();
  }

  function renderFootprint(fp) {
    const emptyEl = document.getElementById("fp-empty");
    const bodyEl = document.getElementById("fp-body");
    const counts = (fp && fp.counts) || {};
    const nLeft =
      counts.left != null ? counts.left : ((fp && fp.left) || []).length;
    const nRead =
      counts.read != null ? counts.read : ((fp && fp.read) || []).length;
    const nChg =
      counts.changed != null ? counts.changed : ((fp && fp.changed) || []).length;
    const nChk =
      counts.verified != null
        ? counts.verified
        : ((fp && fp.verified) || []).length;
    const any = nLeft + nRead + nChg + nChk > 0;
    if (!fp || !any) {
      if (emptyEl) emptyEl.hidden = false;
      if (bodyEl) bodyEl.hidden = true;
      return;
    }
    if (emptyEl) emptyEl.hidden = true;
    if (bodyEl) bodyEl.hidden = false;
    function fill(ulId, nId, items, n) {
      const ul = document.getElementById(ulId);
      const el = document.getElementById(nId);
      if (!ul || !el) return;
      ul.innerHTML = "";
      el.textContent = String(n);
      (items || []).forEach(function (it) {
        const li = document.createElement("li");
        const a = document.createElement("span");
        a.textContent = it.label || "";
        const b = document.createElement("span");
        b.textContent = it.detail || it.time || it.status || "";
        li.appendChild(a);
        li.appendChild(b);
        ul.appendChild(li);
      });
    }
    fill("fp-left", "fp-left-n", fp.left, nLeft);
    fill("fp-read", "fp-read-n", fp.read, nRead);
    fill("fp-chg", "fp-chg-n", fp.changed, nChg);
    fill("fp-chk", "fp-chk-n", fp.verified, nChk);
    const noUp = document.getElementById("fp-no-upload");
    if (noUp) noUp.textContent = fp.no_upload || "No files or memories were uploaded.";
    const meter = document.getElementById("fp-ctx-meter");
    const lab = document.getElementById("fp-ctx-label");
    if (meter) meter.style.width = (fp.context_pct || 0) + "%";
    if (lab) lab.textContent = fp.context_label || "0 of 16k tokens";
  }

  function clearFootprint() {
    renderFootprint({
      left: [],
      read: [],
      changed: [],
      verified: [],
      counts: { left: 0, read: 0, changed: 0, verified: 0 },
    });
  }

  function setTainted(on) {
    if (on) chipTaint.removeAttribute("hidden");
    else chipTaint.setAttribute("hidden", "");
  }

  function renderHistory(groups) {
    historyList.innerHTML = "";
    chatIndex = [];
    (groups || []).forEach(function (sec) {
      const wrap = document.createElement("div");
      const h = document.createElement("h3");
      h.textContent = sec.section || "";
      wrap.appendChild(h);
      (sec.items || []).forEach(function (it) {
        chatIndex.push(it);
        const b = document.createElement("button");
        b.type = "button";
        b.className = "chat";
        b.textContent = it.title || "Chat";
        if (it.id === activeChatId) b.setAttribute("aria-current", "true");
        b.addEventListener("click", function () {
          openChat(it.id);
          appEl.classList.remove("show-rail");
        });
        b.addEventListener("contextmenu", function (ev) {
          ev.preventDefault();
          ctxChatId = it.id;
          ctxMenu.hidden = false;
          ctxMenu.style.left = ev.clientX + "px";
          ctxMenu.style.top = ev.clientY + "px";
        });
        wrap.appendChild(b);
      });
      historyList.appendChild(wrap);
    });
  }

  async function openChat(id) {
    const a = api();
    if (!a || !a.open_chat) return;
    const res = await a.open_chat(id);
    if (!res || !res.ok) return;
    readonly = !!res.readonly;
    activeChatId = id;
    const doc = res.chat || {};
    chatTitle.textContent = doc.title || "Chat";
    clearRuns();
    (doc.messages || []).forEach(function (m) {
      if (m.role === "user") {
        startRun(m.text || "");
        updateRunMeta(currentRun, { status: "" });
      } else if (m.role === "assistant" && currentRun) {
        showAnswer(m.text || "", m.sources || [], null, null);
      }
    });
    if (!(doc.messages || []).length) showEmptyState();
    if (doc.footprint) {
      // bridge may send ui shape via on_footprint instead
    }
    if (a.get_footprint) {
      try {
        const fp = await a.get_footprint();
        if (fp) renderFootprint(fp);
      } catch (e) {
        /* ignore */
      }
    }
    renderHistory(await a.list_chats());
  }

  async function newChat() {
    const a = api();
    if (!a || !a.new_chat) return;
    const res = await a.new_chat();
    readonly = false;
    activeChatId = null;
    chatTitle.textContent = "New chat";
    setTainted(false);
    showEmptyState();
    clearFootprint();
    if (res && res.history) renderHistory(res.history);
    composer.focus();
  }

  function autoSize() {
    composer.style.height = "auto";
    composer.style.height = Math.min(160, composer.scrollHeight) + "px";
  }
  composer.addEventListener("input", autoSize);

  function sendMessage() {
    if (readonly) {
      showSystemNote("Continue in a new chat");
      return;
    }
    const text = (composer.value || "").trim();
    if (!text) return;
    if (busy) {
      const a = api();
      if (a && a.stop_turn) a.stop_turn();
      return;
    }
    composer.value = "";
    autoSize();
    startRun(text);
    setTurnControls(true);
    pinBottom = true;
    const a = api();
    if (!a || !a.send_message) {
      showSystemNote("Python bridge not ready");
      setTurnControls(false);
      return;
    }
    a.send_message(text);
  }

  composerForm.addEventListener("submit", function (e) {
    e.preventDefault();
    sendMessage();
  });
  composer.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  btnNew.addEventListener("click", function () {
    newChat();
  });

  openRail.addEventListener("click", function () {
    appEl.classList.toggle("show-rail");
    appEl.classList.remove("show-foot");
  });
  openFoot.addEventListener("click", function () {
    appEl.classList.toggle("show-foot");
    appEl.classList.remove("show-rail");
  });
  scrim.addEventListener("click", function () {
    appEl.classList.remove("show-rail", "show-foot");
  });

  document.addEventListener("click", function () {
    ctxMenu.hidden = true;
  });
  ctxDelete.addEventListener("click", async function () {
    const a = api();
    if (!a || !ctxChatId) return;
    const res = await a.delete_chat(ctxChatId);
    if (res && res.history) renderHistory(res.history);
    if (ctxChatId === activeChatId) newChat();
    ctxChatId = null;
  });

  /* ----- command palette ----- */
  function fuzzy(q, text) {
    q = (q || "").toLowerCase();
    text = (text || "").toLowerCase();
    if (!q) return true;
    let i = 0;
    for (let c of q) {
      i = text.indexOf(c, i);
      if (i < 0) return false;
      i++;
    }
    return true;
  }

  function paletteCommands(filter) {
    const base = [
      { id: "new", label: "New chat", kbd: "Ctrl N", run: function () { newChat(); } },
      {
        id: "foot",
        label: "Toggle footprint",
        kbd: "Ctrl .",
        run: function () {
          appEl.classList.toggle("show-foot");
        },
      },
      {
        id: "logs",
        label: "Open logs folder",
        run: async function () {
          const a = api();
          if (a && a.open_logs) await a.open_logs();
        },
      },
      {
        id: "selfcheck",
        label: "Run self-check now",
        run: async function () {
          const a = api();
          if (a && a.run_selfcheck) await a.run_selfcheck();
        },
      },
      {
        id: "copy",
        label: "Copy last answer",
        run: async function () {
          try {
            await navigator.clipboard.writeText(lastAnswerText || "");
          } catch (e) {
            const a = api();
            if (a && a.copy_text) a.copy_text(lastAnswerText || "");
          }
        },
      },
    ];
    chatIndex.forEach(function (c) {
      base.push({
        id: "chat:" + c.id,
        label: "Open: " + (c.title || "Chat"),
        run: function () {
          openChat(c.id);
        },
      });
    });
    return base.filter(function (c) {
      return fuzzy(filter, c.label);
    });
  }

  function renderPalette() {
    const q = paletteInput.value || "";
    paletteItems = paletteCommands(q);
    paletteIndex = Math.min(paletteIndex, Math.max(0, paletteItems.length - 1));
    paletteList.innerHTML = "";
    if (!paletteItems.length) {
      const d = document.createElement("div");
      d.className = "empty-msg";
      d.textContent = "No matches";
      paletteList.appendChild(d);
      return;
    }
    paletteItems.forEach(function (c, i) {
      const li = document.createElement("li");
      if (i === paletteIndex) li.setAttribute("aria-selected", "true");
      const b = document.createElement("button");
      b.type = "button";
      b.innerHTML =
        "<span>" +
        escapeHtml(c.label) +
        "</span>" +
        (c.kbd ? "<kbd>" + escapeHtml(c.kbd) + "</kbd>" : "");
      b.addEventListener("click", function () {
        closePalette();
        c.run();
      });
      li.appendChild(b);
      paletteList.appendChild(li);
    });
  }

  function openPalette() {
    palette.hidden = false;
    paletteInput.value = "";
    paletteIndex = 0;
    renderPalette();
    paletteInput.focus();
  }

  function closePalette() {
    palette.hidden = true;
  }

  paletteInput.addEventListener("input", function () {
    paletteIndex = 0;
    renderPalette();
  });
  paletteInput.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      paletteIndex = Math.min(paletteIndex + 1, paletteItems.length - 1);
      renderPalette();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      paletteIndex = Math.max(paletteIndex - 1, 0);
      renderPalette();
    } else if (e.key === "Enter") {
      e.preventDefault();
      const c = paletteItems[paletteIndex];
      if (c) {
        closePalette();
        c.run();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      closePalette();
    }
  });
  palette.addEventListener("click", function (e) {
    if (e.target === palette) closePalette();
  });

  document.addEventListener("keydown", function (e) {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && (e.key === "n" || e.key === "N")) {
      e.preventDefault();
      newChat();
    } else if (mod && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      if (palette.hidden) openPalette();
      else closePalette();
    } else if (mod && e.key === ".") {
      e.preventDefault();
      appEl.classList.toggle("show-foot");
      appEl.classList.remove("show-rail");
    } else if (e.key === "Escape") {
      if (!palette.hidden) closePalette();
      else appEl.classList.remove("show-rail", "show-foot");
    }
  });

  /* ----- bridge callbacks ----- */
  window.miniai = {
    on_status: function (s) {
      if (!s) return;
      if (modelStatus) modelStatus.textContent = s.model || "Model";
      if (modelLamp) {
        modelLamp.classList.remove("loading", "down");
        if (s.model_state === "loading") modelLamp.classList.add("loading");
        else if (s.model_state === "down") modelLamp.classList.add("down");
      }
      if (memLabel) memLabel.textContent = s.memory_label || "—";
      if (memMeter) {
        memMeter.style.width = (s.memory_pct || 0) + "%";
        memMeter.classList.remove("warn", "danger");
        if (s.memory_level === "warn") memMeter.classList.add("warn");
        if (s.memory_level === "danger") memMeter.classList.add("danger");
      }
      if (selfcheckLabel) {
        let sc = String(s.selfcheck || "not run yet")
          .replace(/^Self-check:\s*/i, "")
          .replace(/\u00b7/g, " of ")
          .trim();
        if (!sc || sc === "…" || sc === "...") sc = "not run yet";
        selfcheckLabel.textContent = sc;
        if (s.selfcheck_level === "danger") {
          selfcheckLabel.style.color = "var(--brick)";
        } else if (s.selfcheck_level === "ok" && sc !== "not run yet") {
          selfcheckLabel.style.color = "var(--verdigris)";
        } else {
          selfcheckLabel.style.color = "var(--muted)";
        }
      }
      if (tokSpeed && s.tok_s != null) {
        tokSpeed.textContent =
          s.tok_s > 0 ? Number(s.tok_s).toFixed(1) + " tok/s" : "—";
      }
      setTainted(!!s.tainted);
    },
    on_history: function (groups) {
      renderHistory(groups || []);
      if (activeChatId && chatTitle) {
        const all = [];
        (groups || []).forEach(function (sec) {
          (sec.items || []).forEach(function (it) {
            all.push(it);
          });
        });
        const hit = all.find(function (it) {
          return it.id === activeChatId;
        });
        if (hit && hit.title) chatTitle.textContent = hit.title;
      }
    },
    on_chat_title: function (payload) {
      if (payload && payload.id) activeChatId = payload.id;
      if (chatTitle && payload && payload.title) {
        chatTitle.textContent = payload.title;
      }
    },
    on_activity: function (payload) {
      setTurnControls(true);
      syncSteps(payload || {});
    },
    on_approval: function (req) {
      setTurnControls(true);
      showApprovalCard(req || {});
    },
    on_stream_delta: function (payload) {
      onStreamDelta((payload && payload.text) || "");
    },
    on_stream_clear: function () {
      onStreamClear();
    },
    on_answer: function (payload) {
      setTurnControls(false);
      showAnswer(
        (payload && payload.text) || "",
        (payload && payload.sources) || [],
        {
          steps: (payload && payload.steps) || [],
          total: (payload && payload.total) || "",
        },
        (payload && payload.check) || null
      );
      setTainted(!!(payload && payload.tainted));
      if (payload && payload.tok_s != null && tokSpeed) {
        tokSpeed.textContent =
          payload.tok_s > 0
            ? Number(payload.tok_s).toFixed(1) + " tok/s"
            : "—";
      }
      if (payload && payload.footprint) renderFootprint(payload.footprint);
    },
    on_footprint: function (fp) {
      renderFootprint(fp || {});
    },
    on_cancelled: function (payload) {
      setTurnControls(false);
      showStoppedPartial((payload && payload.partial) || "");
      if (payload && payload.note) showSystemNote(payload.note);
    },
    on_error: function (msg) {
      setTurnControls(false);
      showSystemNote(String(msg || "Error"));
    },
  };

  // External links via bridge
  document.addEventListener("click", function (e) {
    const a = e.target.closest && e.target.closest("a.md-link, a.src");
    if (!a) return;
    const href = a.getAttribute("href") || "";
    if (/^https?:\/\//i.test(href)) {
      e.preventDefault();
      const bridge = api();
      if (bridge && bridge.open_external) bridge.open_external(href);
    }
  });

  async function boot() {
    showEmptyState();
    clearFootprint();
    const a = api();
    if (a && a.ready) {
      try {
        await a.ready();
      } catch (e) {
        /* ignore */
      }
    }
  }

  // Poll approvals (same as before) in case evaluate_js missed one
  async function pollApprovals() {
    const a = api();
    if (!a || !a.poll_approval) return;
    try {
      const req = await a.poll_approval();
      if (req && req.id) window.miniai.on_approval(req);
    } catch (e) {
      /* bridge not ready */
    }
  }
  setInterval(pollApprovals, 400);

  window.addEventListener("pywebviewready", boot);
  if (api()) boot();
})();
