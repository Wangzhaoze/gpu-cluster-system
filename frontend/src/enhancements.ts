const STYLE_ID = "gpu-lab-ui-enhancements";

type LogTarget = { kind: "jobs" | "debug"; id: string };
let lastLogTarget: LogTarget | null = null;

const nativeFetch = window.fetch.bind(window);
window.fetch = async (...args: Parameters<typeof fetch>) => {
  const input = args[0];
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url;
  const match = url.match(
    /\/api\/(jobs|debug)\/([a-f0-9-]{36})\/logs(?:$|[?#])/,
  );
  if (match) {
    lastLogTarget = {
      kind: match[1] as LogTarget["kind"],
      id: match[2],
    };
  }
  const response = await nativeFetch(...args);
  if (match) queueMicrotask(enhance);
  return response;
};

function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    .log-unavailable {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0 13px;
      border: 1px solid var(--border, #cbd5e1);
      border-radius: 8px;
      background: var(--surface-soft, #f1f5f9);
      color: var(--muted, #94a3b8);
      opacity: .58;
      cursor: not-allowed;
      user-select: none;
      font-size: 14px;
      line-height: 1;
    }
    .log-download-button {
      white-space: nowrap;
    }
  `;
  document.head.appendChild(style);
}

function markPrivateLogs() {
  document.querySelectorAll<HTMLSpanElement>("span.muted").forEach((span) => {
    if (span.textContent?.trim() !== "公开摘要") return;
    span.textContent = "日志";
    span.classList.add("log-unavailable");
    span.setAttribute("aria-disabled", "true");
    span.setAttribute("title", "仅本人或管理员可以查看该记录的日志");
  });
}

function addLogDownload() {
  const modal = document.querySelector<HTMLElement>(
    'section[aria-label="任务日志"]',
  );
  if (!modal) return;

  const head = modal.querySelector<HTMLElement>(".panel-head");
  if (!head || head.querySelector("[data-log-download]")) return;

  const shortId =
    head.querySelector("h2")?.textContent?.split("·").pop()?.trim() || "";
  if (
    !lastLogTarget ||
    lastLogTarget.kind !== "jobs" ||
    !lastLogTarget.id.startsWith(shortId)
  ) {
    return;
  }

  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "下载 TXT";
  button.className = "log-download-button";
  button.dataset.logDownload = "true";
  button.title = "下载完整训练日志为 TXT";
  button.addEventListener("click", () => {
    const anchor = document.createElement("a");
    anchor.href = `/api/jobs/${lastLogTarget!.id}/logs/download`;
    anchor.download = `training-${lastLogTarget!.id}.txt`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  });

  const close = Array.from(head.querySelectorAll("button")).find(
    (item) => item.textContent?.includes("关闭"),
  );
  if (close) head.insertBefore(button, close);
  else head.appendChild(button);
}

function enhance() {
  ensureStyles();
  markPrivateLogs();
  addLogDownload();
}

const observer = new MutationObserver(enhance);
observer.observe(document.documentElement, {
  childList: true,
  subtree: true,
});
enhance();
