/* Injected by capture_v9_ui.py — returns scene name. */
window.__v9Scene = function (name) {
  const app = document.getElementById("app");
  const runs = document.getElementById("runs");
  const palette = document.getElementById("palette");
  app.classList.remove("show-rail", "show-foot");
  if (palette) palette.hidden = true;
  if (name === "empty") {
    runs.innerHTML = "";
    const box = document.createElement("div");
    box.className = "empty";
    box.innerHTML =
      "<h2>Try one of these</h2><div class='examples'>" +
      "<button type='button' class='example'>Move the installer files in my Downloads folder into a folder called Installers.<small>Files</small></button>" +
      "<button type='button' class='example'>What changed in the latest Windows 11 update?<small>Web</small></button>" +
      "<button type='button' class='example'>Write a Python function that counts words in a string, with tests.<small>Code</small></button>" +
      "</div>";
    runs.appendChild(box);
    return "empty";
  }
  if (name === "ticket") {
    runs.innerHTML =
      '<article class="run"><div class="ask"><p>Move the installer files in my Downloads folder into Installers.</p>' +
      '<div class="meta"><span><b>10:58</b></span><span>Waiting for you</span><span><b>2</b> steps</span><span><b>Nothing</b> left this PC</span></div></div>' +
      '<ol class="trace">' +
      '<li class="step" data-k="read"><span class="node"><i></i></span><span class="what">Listed Downloads<small>31 files</small></span><span class="t">0.4 s</span></li>' +
      '<li class="ticket" id="v9ticket"><h4>Move 5 files</h4>' +
      '<div class="rows"><span class="path">Downloads\\\\ChromeSetup.exe  -&gt;  Downloads\\\\Installers\\\\ChromeSetup.exe</span>' +
      "<p>Files leave their current folders and appear at the new paths.</p></div>" +
      '<div class="actions"><button class="btn primary" type="button">Move 5 files</button>' +
      '<button class="btn" type="button">Don\'t move</button></div></li></ol></article>';
    return "ticket";
  }
  if (name === "approved") {
    window.__v9Scene("ticket");
    const t = document.getElementById("v9ticket");
    if (t) {
      t.className = "ticket done";
      t.innerHTML = "<h4>You approved: move 5 files, 10:58</h4>";
    }
    const tr = document.querySelector(".trace");
    tr.insertAdjacentHTML(
      "beforeend",
      '<li class="step" data-k="change"><span class="node"><i></i></span><span class="what">Moved 5 files into Downloads\\\\Installers</span><span class="t">0.2 s</span></li>' +
        '<li class="step" data-k="verify"><span class="node"><i></i></span><span class="what">Checked the claim against what actually happened<small>All 5 moves confirmed on disk</small></span><span class="t">0.1 s</span></li>'
    );
    return "approved";
  }
  if (name === "web") {
    runs.innerHTML =
      '<article class="run"><div class="ask"><p>What changed in the latest Windows 11 update?</p>' +
      '<div class="meta"><span><b>11:04</b></span><span>Working</span><span><b>2</b> steps</span><span><b>3 searches</b> left this PC</span></div></div>' +
      '<ol class="trace">' +
      '<li class="step" data-k="out"><span class="node"><i></i></span><span class="what">Searched the web<small>Only the search words left this PC</small></span><span class="t">7 s</span></li>' +
      '<li class="step live" data-k="out"><span class="node"><i></i></span><span class="what">Fetching a page<small>support.microsoft.com</small></span><span class="t"></span></li>' +
      '</ol><div class="answer"><p class="stream-raw">The October update adds a Copilot voice mode<span class="caret"></span></p></div></article>';
    return "web";
  }
  if (name === "foot") {
    window.__v9Scene("web");
    app.classList.add("show-foot");
    document.getElementById("fp-left-n").textContent = "3";
    document.getElementById("fp-left").innerHTML =
      "<li><span>Search: Windows 11 October update</span><span>11:04</span></li>";
    document.getElementById("fp-read-n").textContent = "4";
    document.getElementById("fp-read").innerHTML =
      "<li><span>4 web pages</span><span>untrusted</span></li>";
    return "foot";
  }
  if (name === "palette") {
    window.__v9Scene("empty");
    palette.hidden = false;
    document.getElementById("palette-input").value = "";
    document.getElementById("palette-list").innerHTML =
      '<li aria-selected="true"><button type="button"><span>New chat</span><kbd>Ctrl N</kbd></button></li>' +
      '<li><button type="button"><span>Toggle footprint</span><kbd>Ctrl .</kbd></button></li>' +
      '<li><button type="button"><span>Open logs folder</span></button></li>' +
      '<li><button type="button"><span>Run self-check now</span></button></li>' +
      '<li><button type="button"><span>Copy last answer</span></button></li>';
    return "palette";
  }
  if (name === "narrow") {
    window.__v9Scene("ticket");
    app.classList.add("show-rail");
    return "narrow";
  }
  return "unknown";
};
