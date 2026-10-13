/* No dependencies. Only the rendered article is copied, never dashboard controls. */
(function (root) {
  "use strict";
  function selectArticle(article, doc) {
    const range = doc.createRange();
    range.selectNodeContents(article);
    const selection = doc.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  async function copyArticle(article, env = root) {
    const html = article.innerHTML;
    const text = article.innerText;
    if (env.isSecureContext && env.navigator.clipboard && env.ClipboardItem) {
      try {
        await env.navigator.clipboard.write([new env.ClipboardItem({
          "text/html": new env.Blob([html], { type: "text/html" }),
          "text/plain": new env.Blob([text], { type: "text/plain" })
        })]);
        return "Copied with formatting. Paste into your Substack draft.";
      } catch (_) { /* Browser permission or format support: try a user-initiated legacy copy. */ }
    }
    const doc = env.document;
    let handled = false;
    const onCopy = (event) => {
      if (!event.clipboardData) return;
      event.clipboardData.setData("text/html", html);
      event.clipboardData.setData("text/plain", text);
      event.preventDefault();
      handled = true;
    };
    selectArticle(article, doc);
    doc.addEventListener("copy", onCopy);
    let copied = false;
    try { copied = Boolean(doc.execCommand && doc.execCommand("copy")); }
    catch (_) { /* Leave the article selected for the manual fallback. */ }
    finally { doc.removeEventListener("copy", onCopy); }
    if (copied && handled) {
      doc.getSelection().removeAllRanges();
      return "Copied with formatting. Paste into your Substack draft.";
    }
    return "Automatic copy is unavailable. The article is selected: press Ctrl+C or ⌘C (on mobile, choose Copy). Use HTTPS or localhost for one-click copying.";
  }
  root.FrenchDashboard = { copyArticle };
  if (!root.document || !root.document.querySelector) return;

  const doc = root.document;
  const copy = doc.querySelector("#copy-button");
  if (copy) copy.addEventListener("click", async () => {
    copy.disabled = true;
    try { doc.querySelector("#copy-status").textContent = await copyArticle(doc.querySelector("#article")); }
    finally { copy.disabled = false; }
  });

  async function post(path) {
    const response = await fetch(path, {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRF-Token": doc.querySelector('meta[name="csrf-token"]').content }
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "Request failed. Please refresh and try again.");
    return body;
  }
  const status = doc.querySelector("#job-status");
  const generate = doc.querySelector("#generate-button");
  if (generate) generate.addEventListener("click", async () => {
    generate.disabled = true;
    try {
      const result = await post("/api/generate");
      status.textContent = result.message;
      if (result.exists) root.location.reload();
    } catch (error) { status.textContent = error.message; generate.disabled = false; }
  });
  const approve = doc.querySelector("#approve-button");
  if (approve) approve.addEventListener("click", async () => {
    approve.disabled = true;
    try { await post("/api/approve/" + approve.dataset.day); root.location.reload(); }
    catch (error) { status.textContent = error.message; approve.disabled = false; }
  });
  // Poll only the missing-today page. Never replace a past article being read or copied.
  if (generate) {
    const timer = root.setInterval(async () => {
      try {
        const response = await fetch("/api/status", { credentials: "same-origin" });
        if (!response.ok) { root.clearInterval(timer); return; }
        const info = await response.json();
        if (info.exists || info.today !== doc.body.dataset.today) { root.location.reload(); return; }
        generate.disabled = info.busy;
        generate.textContent = info.busy ? "Generating…" : "Generate today’s lesson";
        if (info.job || info.notice) status.textContent = info.job ? info.job.message : info.notice;
      } catch (_) { status.textContent = "Connection interrupted. Reconnecting…"; }
    }, 5000);
  }
})(globalThis);
