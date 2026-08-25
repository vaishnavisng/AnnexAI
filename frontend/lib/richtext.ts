function escapeHtml(text: string): string {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function normalizeCodeLang(raw: string): string {
  const aliasMap: Record<string, string> = {
    js: "javascript", ts: "typescript", py: "python",
    sh: "bash", shell: "bash", zsh: "bash", yml: "yaml",
    html: "markup", xml: "markup",
  };
  const cleaned = String(raw || "").trim().toLowerCase().replace(/[^a-z0-9+#.-]/g, "");
  return aliasMap[cleaned] || cleaned || "text";
}

function formatInline(text: string): string {
  return escapeHtml(text)
    .replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
}

function renderCodeBlock(rawCode: string, rawLang: string): string {
  const lang = normalizeCodeLang(rawLang);
  const langLabel = escapeHtml(rawLang || lang || "text");
  const code = escapeHtml(rawCode || "");
  return `
    <div class="code-block">
      <div class="code-block-header">
        <span class="code-block-lang">${langLabel}</span>
        <button type="button" class="code-copy-btn">Copy</button>
      </div>
      <pre><code class="language-${lang}">${code}</code></pre>
    </div>
  `;
}

export function renderRichText(raw: string): string {
  const lines = String(raw || "").replace(/\r/g, "").split("\n");
  const html: string[] = [];
  let inUl = false, inOl = false, inCode = false;
  let codeLang = "", codeLines: string[] = [];

  const closeLists = () => {
    if (inUl) { html.push("</ul>"); inUl = false; }
    if (inOl) { html.push("</ol>"); inOl = false; }
  };

  const closeCodeBlock = () => {
    if (!inCode) return;
    html.push(renderCodeBlock(codeLines.join("\n"), codeLang));
    inCode = false; codeLang = ""; codeLines = [];
  };

  for (const rawLine of lines) {
    const fence = rawLine.match(/^```\s*([a-zA-Z0-9_+#.-]*)\s*$/);
    if (fence) {
      if (inCode) { closeCodeBlock(); } else { closeLists(); inCode = true; codeLang = fence[1] || ""; codeLines = []; }
      continue;
    }
    if (inCode) { codeLines.push(rawLine); continue; }

    const line = rawLine.trim();
    if (!line) { closeLists(); continue; }

    if (line.match(/^(?:---+|___+|\*\*\*+)$/)) { closeLists(); html.push("<hr>"); continue; }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) { closeLists(); const level = Math.min(4, heading[1].length); html.push(`<h${level}>${formatInline(heading[2])}</h${level}>`); continue; }

    const ordered = line.match(/^\d+[.)]\s+(.*)$/);
    if (ordered) { if (!inOl) { closeLists(); html.push("<ol>"); inOl = true; } html.push(`<li>${formatInline(ordered[1])}</li>`); continue; }

    const bullet = line.match(/^[-*]\s+(.*)$/);
    if (bullet) { if (!inUl) { closeLists(); html.push("<ul>"); inUl = true; } html.push(`<li>${formatInline(bullet[1])}</li>`); continue; }

    const quote = line.match(/^>\s?(.*)$/);
    if (quote) { closeLists(); html.push(`<blockquote>${formatInline(quote[1])}</blockquote>`); continue; }

    closeLists();
    html.push(`<p>${formatInline(line)}</p>`);
  }

  closeLists();
  closeCodeBlock();
  return html.join("");
}

export function enhanceCodeBlocks(root: HTMLElement | null) {
  if (!root) return;
  root.querySelectorAll<HTMLButtonElement>(".code-copy-btn").forEach((btn) => {
    if (btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", async () => {
      const codeNode = btn.closest(".code-block")?.querySelector("code");
      const text = codeNode?.textContent || "";
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        btn.classList.add("is-copied");
        btn.textContent = "Copied";
        setTimeout(() => { btn.classList.remove("is-copied"); btn.textContent = "Copy"; }, 1200);
      } catch { btn.textContent = "Failed"; setTimeout(() => { btn.textContent = "Copy"; }, 1200); }
    });
  });
}
