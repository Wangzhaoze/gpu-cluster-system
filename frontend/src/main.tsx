import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type {
  User,
  Environment,
  Workload,
  Workspace,
  Slot,
  QueueItem,
  Variable,
  Storage,
  Audit,
  Remote,
  DockerImage,
} from "./types";
import "./styles.css";

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch("/api" + path, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new ApiError(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail || response.status),
      response.status,
    );
  return data;
}
const date = (s: string | null) =>
  s
    ? new Date(s).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
const size = (n: number) =>
  n >= 1073741824
    ? (n / 1073741824).toFixed(2) + " GB"
    : (n / 1048576).toFixed(1) + " MB";
const terminal = ["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT", "REJECTED"];
const statusName: Record<string, string> = {
  PENDING: "排队中",
  STARTING: "启动中",
  RUNNING: "运行中",
  COMPLETED: "已完成",
  FAILED: "失败",
  CANCELLED: "已取消",
  TIMED_OUT: "已超时",
  FREE: "空闲",
  STOPPED: "已停止",
  AWAITING_APPROVAL: "等待管理员审批",
  REJECTED: "审批未通过",
  EXTERNAL_BUSY: "外部占用",
};
const loginFailure: Record<string, string> = {
  unknown_user: "用户名不存在",
  disabled: "账号已停用",
  bad_password: "密码不匹配",
};
function auditDetail({ action, metadata: m }: Audit) {
  if (action === "login.failed")
    return [
      loginFailure[String(m.reason)] || String(m.reason),
      `输入的用户名 ${JSON.stringify(m.username)}`,
      `输入的密码 ${m.password_length} 位`,
      ...((m.password_notes as string[]) || []),
      `来源 ${m.client}`,
      m.user_agent,
    ]
      .filter(Boolean)
      .join(" · ");
  if (action === "login")
    return [
      m.password_normalized && "已忽略密码中的全角/不可见字符或首尾空白",
      m.client && `来源 ${m.client}`,
      m.user_agent,
    ]
      .filter(Boolean)
      .join(" · ");
  return Object.keys(m).length ? JSON.stringify(m) : "";
}
function Status({ value }: { value: string }) {
  return (
    <span className={"status status-" + value.toLowerCase()}>
      <i />
      {statusName[value] || value}
    </span>
  );
}
function Icon({ name }: { name: string }) {
  const paths: Record<string, string> = {
    dashboard: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
    workspace: "M3 4h18v13H3z M8 21h8 M12 17v4 M7 9l3 3-3 3 M13 14h4",
    jobs: "M8 3h8v4H8z M8 5H5v16h14V5h-3 M8 11h8 M8 15h6",
    debug:
      "M9 3l3 3 3-3 M7 9h10v8a5 5 0 01-10 0z M3 10h4 M17 10h4 M3 16h4 M17 16h4 M12 9v12",
    environment: "M12 2l9 5v10l-9 5-9-5V7z M3 7l9 5 9-5 M12 12v10",
    users:
      "M9 13a4 4 0 100-8 4 4 0 000 8z M2 22v-3a7 7 0 0114 0v3 M17 5a4 4 0 010 8 M20 22v-3a6 6 0 00-3-5",
    storage: "M3 5h18v5H3z M3 14h18v5H3z M6 7h1 M6 16h1",
    audit: "M5 3h14v18H5z M8 7h8 M8 11h8 M8 15h5",
    remote:
      "M2 12a10 10 0 1020 0 10 10 0 00-20 0 M2 12h20 M12 2a20 20 0 010 20 20 20 0 010-20",
    account: "M12 13a4 4 0 100-8 4 4 0 000 8z M4 22v-2a8 8 0 0116 0v2",
  };
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={paths[name] || paths.jobs} />
    </svg>
  );
}
function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

const metric = (value: number | null | undefined, unit: string) =>
  value == null ? "—" : Math.round(value * 10) / 10 + unit;

function GpuPicker({ slots, max, initial }: { slots: Slot[]; max: number; initial: number }) {
  const [mode, setMode] = useState(initial && max ? "auto" : "cpu");
  const [count, setCount] = useState(Math.min(initial || 1, max));
  const [selected, setSelected] = useState<number[]>([]);
  const gpuCount = mode === "cpu" ? 0 : mode === "manual" ? selected.length : count;
  return <div className="gpu-picker">
    <Field label="显卡分配">
      <select value={mode} onChange={(e) => {
        setMode(e.target.value);
        if (e.target.value === "auto" && count < 1 && max) setCount(1);
        if (e.target.value === "manual" && !selected.length) {
          const first = slots.find((s) => s.state === "FREE" && !s.external_busy) || slots[0];
          if (first && max) setSelected([first.gpu_index]);
        }
      }}>
        <option value="cpu">仅 CPU</option>
        <option value="auto" disabled={!max}>自动分配空闲显卡</option>
        <option value="manual" disabled={!max}>指定显卡</option>
      </select>
    </Field>
    <input type="hidden" name="gpu_mode" value={mode} />
    <input type="hidden" name="gpu" value={gpuCount} />
    <input type="hidden" name="gpu_indices" value={JSON.stringify(mode === "manual" ? selected : null)} />
    {mode === "auto" && <Field label="GPU 数量"><input type="number" min="1" max={max}
      value={count} required onChange={(e) => setCount(Number(e.target.value))} /></Field>}
    {mode === "manual" && <div className="gpu-choices">{slots.map((s) => <label key={s.gpu_index}>
      <input type="checkbox" checked={selected.includes(s.gpu_index)}
        disabled={!selected.includes(s.gpu_index) && selected.length >= max}
        onChange={(e) => setSelected(e.target.checked ? [...selected, s.gpu_index] : selected.filter((i) => i !== s.gpu_index))} />
      <span>GPU {s.gpu_index} · {s.state !== "FREE" ? "平台占用" : s.external_busy ? "外部占用" : "空闲"}
        <small>{metric(s.metrics?.utilization_percent, "%")} · {metric(s.metrics?.temperature_c, "°C")}</small></span>
    </label>)}</div>}
    {mode === "manual" && <p className="muted">最多 {max} 张；指定显卡被占用时等待该卡释放，不会改用其他显卡。</p>}
  </div>;
}

function App() {
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true),
    [page, setPage] = useState("dashboard");
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [connectionError, setConnectionError] = useState("");
  const [showLoginPassword, setShowLoginPassword] = useState(false);
  const [resources, setResources] = useState<{
    mode: string;
    worker_online: boolean;
    slots: Slot[];
    telemetry_status: string;
    telemetry_sampled_at: string | null;
    telemetry_error: string | null;
  }>({ mode: "mock-docker", worker_online: false, slots: [], telemetry_status: "unavailable", telemetry_sampled_at: null, telemetry_error: null });
  const [debugHours, setDebugHours] = useState(1);
  const [workspace, setWorkspace] = useState<Workspace | null>(null),
    [jobs, setJobs] = useState<Workload[]>([]),
    [debug, setDebug] = useState<Workload[]>([]),
    [queue, setQueue] = useState<QueueItem[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]),
    [users, setUsers] = useState<User[]>([]),
    [storage, setStorage] = useState<Storage[]>([]),
    [audit, setAudit] = useState<Audit[]>([]);
  const [images, setImages] = useState<DockerImage[]>([]);
  const [variables, setVariables] = useState<Variable[]>([]),
    [scope, setScope] = useState("global"),
    [remote, setRemote] = useState<Remote>({ status: "offline", url: null });
  const [logTarget, setLogTarget] = useState<Workload | null>(null),
    [log, setLog] = useState(""),
    [editing, setEditing] = useState<User | null>(null);
  const [invitation, setInvitation] = useState<{
    username: string;
    password: string;
    url: string;
  } | null>(null);
  function endSession(message = "") {
    setUser(null);
    setPage("dashboard");
    setInvitation(null);
    setEditing(null);
    setLogTarget(null);
    setShowLoginPassword(false);
    setError("");
    setConnectionError("");
    setNotice(message);
  }
  useEffect(() => {
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);
  const refresh = useCallback(async () => {
    if (!user) return;
    const [r, w, j, d, q, e, t] = await Promise.all([
      api<typeof resources>("/resources/gpus"),
      api<Workspace>("/workspace"),
      api<Workload[]>("/jobs"),
      api<Workload[]>("/debug"),
      api<QueueItem[]>("/resources/queue"),
      api<Environment[]>("/environments"),
      api<Remote>("/system/remote-access"),
    ]);
    setResources(r);
    setWorkspace(w);
    setJobs(j);
    setDebug(d);
    setQueue(q);
    setEnvironments(e);
    setRemote(t);
    if (user.role === "ADMIN") {
      const [u, s, a, i] = await Promise.all([
        api<User[]>("/users"),
        api<Storage[]>("/admin/storage"),
        api<Audit[]>("/admin/audit"),
        api<DockerImage[]>("/admin/images"),
      ]);
      setUsers(u);
      setStorage(s);
      setAudit(a);
      setImages(i);
    } else {
      setStorage([await api<Storage>("/storage")]);
    }
  }, [user]);
  useEffect(() => {
    if (!user) return;
    const load = () =>
      refresh()
        .then(() => setConnectionError(""))
        .catch((e) => {
          if (e instanceof ApiError && e.status === 401)
            endSession("登录已失效，请重新登录。");
          else setConnectionError(e.message);
        });
    load();
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [refresh, user]);
  useEffect(() => {
    if (user)
      api<Variable[]>(
        "/settings/env" + (scope === "global" ? "" : "?user_id=" + scope),
      )
        .then(setVariables)
        .catch((e) => setConnectionError(e.message));
  }, [scope, user, page]);
  useEffect(() => {
    if (!logTarget) return;
    const load = () =>
      api<{ log: string }>(
        "/" +
          (logTarget.kind === "debug" ? "debug" : "jobs") +
          "/" +
          logTarget.id +
          "/logs",
      )
        .then((r) => setLog(r.log))
        .catch((e) => setError(e.message));
    load();
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [logTarget]);
  async function act(action: () => Promise<unknown>, message = "操作成功") {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await action();
      await refresh();
      setNotice(message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function deleteResource(path: string, description: string) {
    if (user?.role !== "ADMIN" || !window.confirm(description + "\n此操作无法撤销，确认删除？")) return;
    act(async () => {
      await api(path, "DELETE");
      setEditing(null);
      setLogTarget(null);
    }, "已删除");
  }
  const submit = (
    event: React.FormEvent<HTMLFormElement>,
    action: (data: FormData) => Promise<unknown>,
    message: string,
    reset = false,
  ) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    act(async () => {
      await action(data);
      if (reset) form.reset();
    }, message);
  };
  const txt = (f: FormData, k: string) => String(f.get(k) || "");
  const num = (f: FormData, k: string) => Number(f.get(k));
  const gpuIndices = (f: FormData): number[] | null => {
    const indices = JSON.parse(txt(f, "gpu_indices") || "null");
    if (txt(f, "gpu_mode") === "manual" && !indices?.length) throw new Error("请至少选择一张显卡");
    return indices;
  };
  const envOptions = environments.filter(
    (e) =>
      e.enabled &&
      e.available !== false &&
      (user?.role === "ADMIN" || e.id === user?.default_environment_id),
  );
  const activeDebug = debug.filter((d) => !terminal.includes(d.status));
  const nav = [
    ["dashboard", "总览"],
    ["workspace", "工作区"],
    ["jobs", "训练任务"],
    ["debug", "在线调试"],
    ["environment", "环境"],
    ["storage", "存储"],
    ...(user?.role === "ADMIN"
      ? [
          ["users", "用户管理"],
          ["audit", "操作记录"],
        ]
      : []),
    ["remote", "远程访问"],
    ["account", "我的账号"],
  ];
  if (loading) return <div className="loading">正在连接 GPU Lab…</div>;
  if (!user)
    return (
      <div className="login-page">
        <div className="login-story">
          <div className="brand">
            <span className="logo">G</span> GPU LAB
          </div>
          <span className="eyebrow">YOUR LAB, CONNECTED</span>
          <h1>
            从想法到实验。
            <br />
            让算力随时就绪。
          </h1>
          <p>
            一个工作区，一套持久化环境。
            <br />
            在浏览器中编写、调试、运行你的研究。
          </p>
          <div className="login-diagram">
            WORKSPACE <span>→</span> DEBUG <span>→</span> TRAIN
          </div>
          <small>Ubuntu Docker · 实验室算力平台</small>
        </div>
        <div className="login-card">
          <span className="eyebrow">WELCOME BACK</span>
          <h2>登录实验室</h2>
          <p className="muted">使用管理员分配的 Portal 账号。</p>
          {notice && <p className="alert success">{notice}</p>}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              setError("");
              setBusy(true);
              api<User>("/auth/login", "POST", {
                username: txt(f, "username").trim().toLowerCase(),
                password: txt(f, "password"),
              })
                .then((u) => {
                  setUser(u);
                  setShowLoginPassword(false);
                  setNotice("");
                })
                .catch((e) =>
                  setError(
                    e instanceof ApiError && e.status === 401
                      ? "用户名或密码错误。请确认复制的是账号和密码本身；密码区分大小写，不要包含标签、引号或多余空格。"
                      : e.message,
                  ),
                )
                .finally(() => setBusy(false));
            }}
          >
            <Field label="用户名">
              <input
                name="username"
                placeholder="管理员分配的用户名"
                autoComplete="username"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                required
              />
            </Field>
            <Field label="密码">
              <input
                name="password"
                type={showLoginPassword ? "text" : "password"}
                autoComplete="current-password"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                required
              />
            </Field>
            <button
              type="button"
              aria-pressed={showLoginPassword}
              className="generate-password"
              onClick={() => setShowLoginPassword(!showLoginPassword)}
            >
              {showLoginPassword ? "隐藏密码" : "查看密码"}
            </button>
            {error && <div className="alert error">{error}</div>}
            <button className="primary wide" disabled={busy}>
              {busy ? "正在登录…" : "登录 →"}
            </button>
          </form>
          <p className="login-note">文件与 Python 包持续保存，容器按需启动。</p>
        </div>
      </div>
    );
  return (
    <div className="app-shell">
      <aside>
        <div className="brand">
          <span className="logo">G</span>
          <div>
            GPU LAB<small>RESEARCH PLATFORM</small>
          </div>
        </div>
        <div className="sidebar-label">实验室</div>
        <nav>
          {nav.map(([id, label]) => (
            <button
              key={id}
              className={page === id ? "selected" : ""}
              onClick={() => {
                setPage(id);
                setError("");
                setNotice("");
                setInvitation(null);
              }}
            >
              <Icon name={id} />
              {label}
              {id === "jobs" && queue.length > 0 && <b>{queue.length}</b>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div
            className={
              "connection " + (resources.worker_online ? "online" : "")
            }
          >
            <i />
            {resources.worker_online ? "调度服务在线" : "等待调度服务"}
          </div>
          <div className="profile">
            <span className="avatar">{user.display_name.slice(0, 1)}</span>
            <div>
              <strong>{user.display_name}</strong>
              <small>{user.role === "ADMIN" ? "管理员" : "实验室成员"}</small>
            </div>
            <button
              title="退出登录"
              onClick={() =>
                api("/auth/logout", "POST").then(() => endSession())
              }
            >
              ↪
            </button>
          </div>
        </div>
      </aside>
      <div className="main">
        <header>
          <span>
            实验室 / <strong>{nav.find((n) => n[0] === page)?.[1]}</strong>
          </span>
          <span
            className={
              "mode " + (resources.mode === "mock-docker" ? "mock" : "real")
            }
          >
            {resources.mode === "mock-docker"
              ? "MOCK GPU MODE"
              : "LOCAL GPU MODE"}
          </span>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <span className="eyebrow">GPU LAB / {page.toUpperCase()}</span>
              <h1>{nav.find((n) => n[0] === page)?.[1]}</h1>
              <p className="muted">
                {page === "dashboard"
                  ? "算力、任务和工作区，尽在这里。"
                  : page === "workspace"
                    ? "持续保存你的代码和 Python 环境。"
                    : page === "jobs"
                      ? "提交实验，由调度器分配资源并保留运行日志。"
                      : page === "debug"
                        ? "按需开启带 GPU 的浏览器调试会话。"
                        : page === "environment"
                          ? "固定镜像版本，复用同一个 Python 环境。"
                          : "管理你的实验室资源。"}
              </p>
            </div>
            {page === "dashboard" && (
              <button className="primary" onClick={() => setPage("jobs")}>
                ＋ 新建训练
              </button>
            )}
          </div>
          {connectionError && (
            <div role="status" className="alert error">
              服务连接暂时中断，正在自动重试…
            </div>
          )}
          {error && (
            <div role="alert" className="alert error">
              {error}
              <button onClick={() => setError("")}>×</button>
            </div>
          )}
          {notice && (
            <div role="status" className="alert success">
              {notice}
              <button onClick={() => setNotice("")}>×</button>
            </div>
          )}
          {page === "dashboard" && (
            <>
              <div className="stats">
                <div>
                  <span>可用 GPU</span>
                  <strong>
                    {resources.mode === "local-gpu-docker" && resources.telemetry_status !== "online" ? "—" :
                      resources.slots.filter((s) => s.state === "FREE" && !s.external_busy).length}
                    <small> / {resources.slots.length}</small>
                  </strong>
                </div>
                <div>
                  <span>运行中的任务</span>
                  <strong>
                    {queue.filter((q) => q.status !== "PENDING").length}
                  </strong>
                </div>
                <div>
                  <span>等待调度</span>
                  <strong>
                    {queue.filter((q) => q.status === "PENDING").length}
                  </strong>
                </div>
                <div>
                  <span>我的工作区</span>
                  <strong className="small-stat">
                    {workspace?.state === "RUNNING" ? "运行中" : "已停止"}
                  </strong>
                </div>
              </div>
              <section className="panel">
                <div className="panel-head">
                  <h2>GPU 资源</h2>
                  <span className="muted">每 3 秒采样 · 独占分配 · FIFO 队列</span>
                </div>
                <p className="muted">{resources.telemetry_status === "online"
                  ? "最近采样：" + new Date(resources.telemetry_sampled_at!).toLocaleTimeString("zh-CN")
                  : resources.telemetry_status === "mock" ? "模拟模式，无真实硬件读数"
                  : (resources.telemetry_error || "GPU 监控暂不可用") + "；等待恢复，不显示过期读数"}</p>
                <div className="gpu-grid">
                  {resources.slots.map((s) => (
                    <div
                      key={s.gpu_index}
                      className={
                        "gpu-card " +
                        (s.state === "FREE" && !s.external_busy ? "available" : "occupied")
                      }
                    >
                      <div>
                        <span className="chip-icon">▦</span>
                        <small>
                          {resources.mode === "mock-docker"
                            ? "VIRTUAL"
                            : "NVIDIA"}
                        </small>
                      </div>
                      <h3>GPU {s.gpu_index}</h3>
                      <strong className="gpu-model">{s.metrics?.name || (resources.mode === "mock-docker" ? "模拟显卡" : "NVIDIA 显卡")}</strong>
                      <Status value={s.external_busy ? "EXTERNAL_BUSY" : s.state} />
                      <p>{s.username || (s.external_busy ? "外部计算进程占用，等待释放" : "平台尚未分配")}</p>
                      <dl className="gpu-metrics">
                        <dt>GPU 利用率</dt><dd>{metric(s.metrics?.utilization_percent, "%")}</dd>
                        <dt>显存</dt><dd>{metric(s.metrics?.memory_used_mb, "")} / {metric(s.metrics?.memory_total_mb, " MiB")}</dd>
                        <dt>显存控制器利用率</dt><dd>{metric(s.metrics?.memory_utilization_percent, "%")}</dd>
                        <dt>温度</dt><dd>{metric(s.metrics?.temperature_c, "°C")}</dd>
                        <dt>功耗 / 上限</dt><dd>{metric(s.metrics?.power_w, "")} / {metric(s.metrics?.power_limit_w, " W")}</dd>
                        <dt>风扇</dt><dd>{metric(s.metrics?.fan_percent, "%")}</dd>
                        <dt>核心 / 显存频率</dt><dd>{metric(s.metrics?.graphics_clock_mhz, "")} / {metric(s.metrics?.memory_clock_mhz, " MHz")}</dd>
                        <dt>计算进程数</dt><dd>{s.metrics?.compute_process_count ?? "—"}</dd>
                      </dl>
                      {s.metrics && <details className="gpu-details"><summary>硬件详情</summary>
                        <div>驱动：{s.metrics.driver_version}<br />PCI：{s.metrics.pci_bus_id}<br />UUID：{s.metrics.uuid}</div>
                      </details>}
                      <small>
                        {s.owner_type === "train"
                          ? "TRAINING"
                          : s.owner_type === "debug"
                            ? "DEBUG"
                            : "READY"}
                      </small>
                    </div>
                  ))}
                </div>
              </section>
              <div className="two-col">
                <section className="panel">
                  <div className="panel-head">
                    <h2>调度队列</h2>
                    <span className="count">{queue.length}</span>
                  </div>
                  {queue.length ? (
                    <div className="queue-list">
                      {queue.map((q, i) => (
                        <div key={q.id}>
                          <span className="queue-number">{i + 1}</span>
                          <div>
                            <strong>{q.username}</strong>
                            <small>
                              {q.kind === "train" ? "训练" : "调试"} ·{" "}
                              {q.requested_gpus} GPU{q.requested_gpu_indices ? " (" + q.requested_gpu_indices.join(", ") + ")" : " (自动)"} · {q.id.slice(0, 8)}
                            </small>
                          </div>
                          <Status value={q.status} />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <Empty text="队列为空，开始一个新实验吧。" />
                  )}
                </section>
                <section className="panel workspace-teaser">
                  <div className="panel-head">
                    <h2>我的工作区</h2>
                    <Icon name="workspace" />
                  </div>
                  <Status value={workspace?.state || "STOPPED"} />
                  <p>浏览器 VS Code</p>
                  <span className="muted">
                    CPU 工作区不占用 GPU。你的文件和安装的 Python 包会保留。
                  </span>
                  <div className="actions">
                    <button
                      className="primary"
                      disabled={busy}
                      onClick={() =>
                        workspace?.state === "RUNNING"
                          ? window.open(
                              workspace.route_path,
                              "_blank",
                              "noopener",
                            )
                          : act(
                              () => api("/workspace/start", "POST"),
                              "工作区已启动",
                            )
                      }
                    >
                      {workspace?.state === "RUNNING"
                        ? "打开 VS Code ↗"
                        : "启动工作区"}
                    </button>
                    <button onClick={() => setPage("workspace")}>
                      查看详情
                    </button>
                  </div>
                </section>
              </div>
            </>
          )}
          {page === "workspace" && workspace && (
            <>
              <section className="panel">
                <div className="panel-head">
                  <h2>{user.username} 的工作区</h2>
                  <Status value={workspace.state} />
                </div>
                <div className="detail-grid">
                  <div>
                    <span>环境镜像</span>
                    <strong>{workspace.environment.name}</strong>
                    <code>{workspace.environment.image_version}</code>
                  </div>
                  <div>
                    <span>持久化 Python 环境</span>
                    <code>{workspace.venv}</code>
                  </div>
                  <div>
                    <span>算力</span>
                    <strong>CPU · 2 核 / 2 GB</strong>
                    <small>GPU 由 Debug 或 Training 分配</small>
                  </div>
                </div>
                <div className="actions">
                  <button
                    className="primary"
                    disabled={busy || workspace.state === "RUNNING"}
                    onClick={() =>
                      act(() => api("/workspace/start", "POST"), "工作区已启动")
                    }
                  >
                    启动
                  </button>
                  <button
                    disabled={busy || workspace.state !== "RUNNING"}
                    onClick={() =>
                      act(
                        () => api("/workspace/stop", "POST"),
                        "容器已删除，文件与环境已保留",
                      )
                    }
                  >
                    停止
                  </button>
                  <button
                    disabled={busy}
                    onClick={() =>
                      act(
                        () => api("/workspace/restart", "POST"),
                        "工作区已重新创建",
                      )
                    }
                  >
                    重新创建
                  </button>
                  {workspace.state === "RUNNING" && (
                    <a
                      className="button"
                      href={workspace.route_path}
                      target="_blank"
                      rel="noreferrer"
                    >
                      打开 VS Code ↗
                    </a>
                  )}
                  {user.role === "ADMIN" && (
                    <button className="danger" disabled={busy}
                      onClick={() => deleteResource("/workspace", "删除自己的工作区文件、Python 环境和缓存；保留训练结果和任务记录。必须先停止所有调试和训练。")}>删除工作区</button>
                  )}
                </div>
              </section>
              <section className="panel">
                <h2>开始你的实验</h2>
                <p className="muted">
                  点击「启动」，等待运行中后打开 VS Code。在菜单中选择 Terminal
                  → New Terminal。 首次打开时，请自行确认工作目录可信，再选择
                  Trust Folder & Continue。
                </p>
                <div className="detail-grid">
                  <div>
                    <span>编写代码</span>
                    <code>/workspace</code>
                    <small>工作目录，持续保存</small>
                  </div>
                  <div>
                    <span>读取数据</span>
                    <code>/datasets</code>
                    <small>共享数据集，只读</small>
                  </div>
                  <div>
                    <span>保存输出</span>
                    <code>/results</code>
                    <small>训练结果，持续保存</small>
                  </div>
                </div>
                <pre>
                  python -c "import sys; print(sys.executable)"{"\n"}pip install
                  rich{"\n"}python -c "import rich; print('PERSIST_OK')"
                </pre>
              </section>
            </>
          )}
          {page === "jobs" && (
            <>
              <section className="panel">
                <h2>新建训练任务</h2>
                <form
                  onSubmit={(e) =>
                    submit(
                      e,
                      (f) => {
                        let env = {};
                        try {
                          env = JSON.parse(txt(f, "env") || "{}");
                        } catch {
                          throw new Error("环境变量必须是 JSON 对象");
                        }
                        return api("/jobs", "POST", {
                          environment_id: txt(f, "environment_id"),
                          command: txt(f, "command"),
                          workdir: txt(f, "workdir"),
                          requested_gpus: num(f, "gpu"),
                          gpu_indices: gpuIndices(f),
                          requested_cpus: num(f, "cpu"),
                          requested_ram_mb: num(f, "ram"),
                          time_limit_seconds: num(f, "time"),
                          output_name: txt(f, "output"),
                          env,
                        });
                      },
                      "任务已提交到队列",
                    )
                  }
                >
                  <div className="form-grid">
                    <Field label="环境">
                      <select
                        name="environment_id"
                        defaultValue={user.default_environment_id}
                      >
                        {envOptions.map((e) => (
                          <option key={e.id} value={e.id}>
                            {e.name}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="工作目录">
                      <input
                        name="workdir"
                        defaultValue="/workspace"
                        required
                      />
                    </Field>
                    <GpuPicker slots={resources.slots} max={Math.min(user.max_gpus, resources.slots.length)} initial={0} />
                    <Field label="CPU 核数">
                      <input
                        name="cpu"
                        type="number"
                        min="1"
                        max="32"
                        defaultValue="1"
                        required
                      />
                    </Field>
                    <Field label="内存 (MB)">
                      <input
                        name="ram"
                        type="number"
                        min="256"
                        max="65536"
                        defaultValue="1024"
                        required
                      />
                    </Field>
                    <Field label="最长运行时间 (秒)">
                      <input
                        name="time"
                        type="number"
                        min="5"
                        max="604800"
                        defaultValue="3600"
                        required
                      />
                    </Field>
                    <Field label="输出名称">
                      <input
                        name="output"
                        defaultValue="experiment"
                        pattern="[A-Za-z0-9_-]{1,80}"
                        required
                      />
                    </Field>
                    <Field label="环境变量覆盖 (JSON)">
                      <input name="env" defaultValue="{}" />
                    </Field>
                  </div>
                  <Field label="运行命令">
                    <textarea
                      name="command"
                      rows={3}
                      defaultValue={
                        "python -c \"import os; print('TRAIN_OK'); print(os.environ.get('LAB_ASSIGNED_GPUS'))\""
                      }
                      required
                    />
                  </Field>
                  <div className="form-foot">
                    <span className="muted">
                      输出目录通过 $LAB_RESULT_DIR 提供。
                    </span>
                    <button className="primary" disabled={busy}>
                      提交训练 →
                    </button>
                  </div>
                </form>
              </section>
              <section className="panel">
                <div className="panel-head">
                  <h2>训练记录</h2>
                  <span className="muted">自动刷新</span>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>任务 / 命令</th>
                        <th>用户</th>
                        <th>状态</th>
                        <th>GPU</th>
                        <th>提交时间</th>
                        <th>退出码</th>
                        <th>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {jobs.map((j) => (
                        <tr key={j.id}>
                          <td>
                            <strong className="mono">{j.id.slice(0, 8)}</strong>
                            <small className="truncate" title={j.command}>
                              {j.command}
                            </small>
                            {j.error_message && (
                              <small className="text-error">
                                {j.error_message}
                              </small>
                            )}
                          </td>
                          <td>{j.username}</td>
                          <td>
                            <Status value={j.status} />
                            {j.cancel_requested &&
                              !terminal.includes(j.status) && (
                                <small>正在取消…</small>
                              )}
                          </td>
                          <td>
                            {j.assigned_gpus.length
                              ? j.assigned_gpus.join(", ")
                              : j.requested_gpu_indices ? "指定 " + j.requested_gpu_indices.join(", ") : j.requested_gpus + " 自动"}
                          </td>
                          <td>{date(j.created_at)}</td>
                          <td>{j.exit_code ?? "—"}</td>
                          <td>
                            <div className="actions compact">
                              <button
                                onClick={() => {
                                  setLog("加载日志…");
                                  setLogTarget(j);
                                }}
                              >
                                日志
                              </button>
                              {terminal.includes(j.status) ? (
                                <button
                                  disabled={busy}
                                  onClick={() =>
                                    act(
                                      () =>
                                        api("/jobs/" + j.id + "/retry", "POST"),
                                      "已创建重试任务",
                                    )
                                  }
                                >
                                  重试
                                </button>
                              ) : (
                                <button
                                  disabled={busy}
                                  onClick={() =>
                                    act(
                                      () =>
                                        api(
                                          "/jobs/" + j.id + "/cancel",
                                          "POST",
                                        ),
                                      "已请求取消",
                                    )
                                  }
                                >
                                  取消
                                </button>
                              )}
                              {user.role === "ADMIN" && terminal.includes(j.status) && (
                                <button className="danger" disabled={busy}
                                  onClick={() => deleteResource("/jobs/" + j.id, "删除训练记录和日志；保留结果文件。")}>删除记录</button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!jobs.length && <Empty text="还没有训练任务。" />}
                </div>
              </section>
            </>
          )}
          {page === "debug" && (
            <>
              <section className="panel">
                <h2>新建调试会话</h2>
                <form
                  onSubmit={(e) =>
                    submit(
                      e,
                      (f) =>
                        api("/debug", "POST", {
                          environment_id: txt(f, "environment_id"),
                          requested_gpus: num(f, "gpu"),
                          gpu_indices: gpuIndices(f),
                          requested_cpus: num(f, "cpu"),
                          requested_ram_mb: num(f, "ram"),
                          time_limit_seconds: num(f, "hours") * 3600,
                          approval_reason: txt(f, "approval_reason"),
                        }),
                      debugHours > 10 ? "申请已提交，等待管理员审批（暂不占用 GPU）" : "调试会话已进入队列",
                    )
                  }
                >
                  <div className="form-grid">
                    <Field label="环境">
                      <select
                        name="environment_id"
                        defaultValue={user.default_environment_id}
                      >
                        {envOptions.map((e) => (
                          <option key={e.id} value={e.id}>
                            {e.name}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <GpuPicker slots={resources.slots} max={Math.min(1, user.max_gpus, resources.slots.length)} initial={1} />
                    <Field label="会话时长（小时）">
                      <input name="hours" type="number" min="0.5" max="168" step="0.5"
                        value={debugHours} onChange={(e) => setDebugHours(Number(e.target.value))} required />
                    </Field>
                    <Field label={debugHours > 10 ? "审批理由（必填）" : "备注 / 长时调试理由"}>
                      <input name="approval_reason" maxLength={2000} required={debugHours > 10}
                        placeholder="超过 10 小时需管理员审批，最多申请 7 天" />
                    </Field>
                    <Field label="CPU 核数">
                      <input
                        type="number"
                        name="cpu"
                        min="1"
                        max="32"
                        defaultValue="1"
                        required
                      />
                    </Field>
                    <Field label="内存 (MB)">
                      <input
                        type="number"
                        name="ram"
                        min="256"
                        max="65536"
                        defaultValue="2048"
                        required
                      />
                    </Field>
                  </div>
                  <div className="form-foot">
                    <span className="muted">
                      免审批上限 {user.max_debug_hours} 小时；超过 10 小时需管理员审批。时长从容器启动计算，到期释放 GPU。
                    </span>
                    <button className="primary" disabled={busy}>
                      {debugHours > 10 ? "提交审批申请 →" : "开启调试 →"}
                    </button>
                  </div>
                </form>
              </section>
              <section className="panel">
                <h2>调试会话 {user.role === "ADMIN" && debug.some((d) => d.status === "AWAITING_APPROVAL") &&
                  <span className="tag">待审批 {debug.filter((d) => d.status === "AWAITING_APPROVAL").length}</span>}</h2>
                {debug.length ? (
                  debug.map((d) => (
                    <div className="debug-row" key={d.id}>
                      <Icon name="debug" />
                      <div>
                        <strong>
                          {d.username} · {d.id.slice(0, 8)}
                        </strong>
                        <small>
                          申请 {d.time_limit_seconds / 3600} 小时 · {d.requested_gpu_indices ? "指定 GPU " + d.requested_gpu_indices.join(", ") : "自动分配"} ·{" "}
                          {d.assigned_gpus.length
                            ? "GPU " + d.assigned_gpus.join(", ")
                            : "CPU"}{" "}
                          ·{" "}
                          {d.expires_at
                            ? "剩余 " +
                              Math.max(
                                0,
                                Math.ceil(
                                  (new Date(d.expires_at).getTime() -
                                    Date.now()) /
                                    60000,
                                ),
                              ) +
                              " 分钟"
                            : "等待调度"}
                        </small>
                        {d.approval_reason && <small>申请理由：{d.approval_reason}</small>}
                        {d.approval_note && <small>管理员意见：{d.approval_note}</small>}
                      </div>
                      <Status value={d.status} />
                      <div className="actions compact">
                        {user.role === "ADMIN" && d.status === "AWAITING_APPROVAL" && (
                          <><button disabled={busy || d.cancel_requested} onClick={() => {
                            const note = window.prompt("批准 " + d.username + " 的 " + d.time_limit_seconds / 3600 + " 小时调试申请。可填写审批意见：", "");
                            if (note !== null) act(() => api("/debug/" + d.id + "/approve", "POST", {note}), "已批准，进入调度队列");
                          }}>批准</button><button className="danger" disabled={busy || d.cancel_requested} onClick={() => {
                            const note = window.prompt("填写拒绝理由：", "暂不批准此次长时调试");
                            if (note !== null) act(() => api("/debug/" + d.id + "/reject", "POST", {note}), "已拒绝申请");
                          }}>拒绝</button></>
                        )}
                        {d.status === "RUNNING" && (
                          <a
                            className="button"
                            href={d.route_path!}
                            target="_blank"
                            rel="noreferrer"
                          >
                            VS Code ↗
                          </a>
                        )}
                        <button onClick={() => setLogTarget(d)}>日志</button>
                        {!terminal.includes(d.status) && (
                          <button
                            disabled={busy}
                            onClick={() =>
                              act(
                                () => api("/debug/" + d.id + "/stop", "POST"),
                                "已请求停止调试",
                              )
                            }
                          >
                            {d.status === "AWAITING_APPROVAL" ? "撤回申请" : "停止"}
                          </button>
                        )}
                        {user.role === "ADMIN" && terminal.includes(d.status) && (
                          <button className="danger" disabled={busy}
                            onClick={() => deleteResource("/debug/" + d.id, "删除调试记录和日志；保留工作区与结果文件。")}>删除记录</button>
                        )}
                      </div>
                    </div>
                  ))
                ) : (
                  <Empty text="没有调试会话。" />
                )}
              </section>
            </>
          )}
          {page === "users" && (
            <>
              {invitation && (
                <section
                  className="panel invitation-panel"
                  aria-label="新账号登录信息"
                >
                  <div className="panel-head">
                    <h2>账号已创建 · {invitation.username}</h2>
                    <button onClick={() => setInvitation(null)}>
                      关闭信息卡
                    </button>
                  </div>
                  <p>
                    将以下登录信息交给这位成员。初始密码仅在这张卡中临时保留，关闭后可通过「重置密码」重新设置。
                  </p>
                  <div className="form-grid">
                    <Field label="登录地址">
                      <input value={invitation.url} readOnly />
                    </Field>
                    <Field label="成员用户名">
                      <input value={invitation.username} readOnly />
                    </Field>
                    <Field label="成员初始密码">
                      <input
                        type="password"
                        value={invitation.password}
                        readOnly
                      />
                    </Field>
                  </div>
                  <div className="actions">
                    <button
                      className="primary"
                      onClick={() =>
                        navigator.clipboard
                          .writeText(
                            `GPU Lab 登录地址：${invitation.url}\n用户名：${invitation.username}\n初始密码：${invitation.password}\n首次登录后：我的账号 → 修改密码；工作区 → 启动 → 打开 VS Code。`,
                          )
                          .then(() =>
                            setNotice("登录信息已复制，请交给对应成员"),
                          )
                          .catch(() =>
                            setError(
                              "复制失败，请手动记录用户名及你设置的初始密码",
                            ),
                          )
                      }
                    >
                      复制登录信息
                    </button>
                    <button onClick={() => setPage("remote")}>
                      查看远程使用步骤
                    </button>
                  </div>
                  {!remote.url && (
                    <p className="info">
                      当前没有公网入口；这里是本机地址。跨网络使用前，请先启用远程访问并复制新的公网地址。
                    </p>
                  )}
                </section>
              )}
              <section className="panel">
                <h2>
                  {editing ? "编辑 " + editing.username : "添加实验室成员"}
                </h2>
                {!editing && (
                  <p className="muted">
                    为每位成员创建独立账号。用户名为 3–32
                    位小写字母、数字或下划线，以字母开头。一般选择「成员」，GPU
                    上限填 1，Debug 免审批上限填 10 小时；超过 10 小时需单独申请审批。
                  </p>
                )}
                <form
                  key={editing?.id || "new"}
                  onSubmit={(e) =>
                    submit(
                      e,
                      async (f) => {
                        if (editing) {
                          await api("/users/" + editing.id, "PATCH", {
                            display_name: txt(f, "display_name"),
                            role: txt(f, "role"),
                            max_gpus: num(f, "max_gpus"),
                            max_debug_hours: num(f, "max_debug_hours"),
                            default_environment_id: txt(f, "environment_id"),
                          });
                          setEditing(null);
                        } else {
                          const created = await api<User>("/users", "POST", {
                            username: txt(f, "username"),
                            display_name: txt(f, "display_name"),
                            password: txt(f, "password"),
                            role: txt(f, "role"),
                            max_gpus: num(f, "max_gpus"),
                            max_debug_hours: num(f, "max_debug_hours"),
                            default_environment_id: txt(f, "environment_id"),
                          });
                          setInvitation({
                            username: created.username,
                            password: txt(f, "password"),
                            url: remote.url || window.location.origin,
                          });
                        }
                      },
                      "用户已保存",
                      !editing,
                    )
                  }
                >
                  <div className="form-grid">
                    {!editing && (
                      <>
                        <Field label="用户名">
                          <input
                            name="username"
                            pattern="[a-z][a-z0-9_]{2,31}"
                            placeholder="student01"
                            required
                          />
                        </Field>
                        <Field label="初始密码 (至少 12 位)">
                          <input
                            name="password"
                            type="password"
                            minLength={12}
                            maxLength={200}
                            required
                            autoComplete="new-password"
                          />
                          <button
                            type="button"
                            className="generate-password"
                            onClick={(event) => {
                              const input =
                                event.currentTarget.form?.elements.namedItem(
                                  "password",
                                ) as HTMLInputElement;
                              input.value = Array.from(
                                crypto.getRandomValues(new Uint8Array(18)),
                                (byte) => byte.toString(16).padStart(2, "0"),
                              ).join("");
                            }}
                          >
                            生成随机密码
                          </button>
                        </Field>
                      </>
                    )}
                    <Field label="显示名称">
                      <input
                        name="display_name"
                        defaultValue={editing?.display_name || ""}
                        required
                      />
                    </Field>
                    <Field label="角色">
                      <select
                        name="role"
                        defaultValue={editing?.role || "MEMBER"}
                      >
                        <option value="MEMBER">成员</option>
                        <option value="ADMIN">管理员</option>
                      </select>
                    </Field>
                    <Field label="固定环境">
                      <select
                        name="environment_id"
                        defaultValue={
                          envOptions.some(
                            (e) =>
                              e.id ===
                              (editing?.default_environment_id ||
                                envOptions.find((e) => e.recommended)?.id || user.default_environment_id),
                          )
                            ? editing?.default_environment_id ||
                              envOptions.find((e) => e.recommended)?.id || user.default_environment_id
                            : envOptions[envOptions.length - 1]?.id
                        }
                      >
                        {envOptions.map((e) => (
                          <option key={e.id} value={e.id}>
                            {e.name}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="GPU 上限">
                      <input
                        name="max_gpus"
                        type="number"
                        min="0"
                        max={resources.slots.length}
                        defaultValue={
                          editing?.max_gpus ??
                          Math.min(1, resources.slots.length)
                        }
                        required
                      />
                    </Field>
                    <Field label="Debug 免审批上限 (小时，最多 10)">
                      <input
                        name="max_debug_hours"
                        type="number"
                        min="1"
                        max="10"
                        defaultValue={editing?.max_debug_hours ?? 10}
                        required
                      />
                    </Field>
                  </div>
                  <div className="actions">
                    <button className="primary" disabled={busy}>
                      {editing ? "保存修改" : "创建用户"}
                    </button>
                    {editing && (
                      <button type="button" onClick={() => setEditing(null)}>
                        完成编辑
                      </button>
                    )}
                  </div>
                </form>
              </section>
              <section className="panel">
                <h2>实验室成员</h2>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>用户</th>
                        <th>角色</th>
                        <th>GPU 上限</th>
                        <th>状态</th>
                        <th>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((u) => (
                        <tr key={u.id}>
                          <td>
                            <strong>{u.display_name}</strong>
                            <small>{u.username}</small>
                          </td>
                          <td>{u.role}</td>
                          <td>{u.max_gpus}</td>
                          <td>
                            <Status value={u.enabled ? "RUNNING" : "STOPPED"} />
                          </td>
                          <td>
                            <div className="actions compact">
                              <button
                                onClick={() => {
                                  setEditing(u);
                                  window.scrollTo(0, 0);
                                }}
                              >
                                编辑
                              </button>
                              <button
                                disabled={busy || u.id === user.id}
                                onClick={() =>
                                  act(
                                    () =>
                                      api(
                                        "/users/" +
                                          u.id +
                                          "/" +
                                          (u.enabled ? "disable" : "enable"),
                                        "POST",
                                      ),
                                    "用户状态已更新",
                                  )
                                }
                              >
                                {u.enabled ? "停用" : "启用"}
                              </button>
                              <button
                                disabled={busy}
                                onClick={() =>
                                  act(
                                    () =>
                                      api(
                                        "/workspace/stop?user_id=" + u.id,
                                        "POST",
                                      ),
                                    "工作区已停止",
                                  )
                                }
                              >
                                停工作区
                              </button>
                              <button className="danger" disabled={busy}
                                onClick={() => deleteResource("/workspace?user_id=" + u.id,
                                  "删除 " + u.username + " 的工作区文件、Python 环境和缓存；保留账号、任务记录和结果。必须先停止调试和训练。")}>删除工作区</button>
                              <button className="danger" disabled={busy || u.enabled || u.id === user.id}
                                title="请先停用账号并停止所有任务"
                                onClick={() => deleteResource("/users/" + u.id,
                                  "永久删除 " + u.username + " 的账号、工作区、Python 环境、缓存、结果及任务记录；保留审计记录。")}>删除用户</button>
                              <button
                                disabled={busy}
                                onClick={() => {
                                  const password = window.prompt(
                                    "设置 " +
                                      u.username +
                                      " 的新密码 (至少 12 位)",
                                  );
                                  if (password)
                                    act(
                                      () =>
                                        api(
                                          "/users/" + u.id + "/reset-password",
                                          "POST",
                                          { password },
                                        ),
                                      "密码已重置，已有登录失效",
                                    );
                                }}
                              >
                                重置密码
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
          {page === "environment" && (
            <>
              <section className="panel">
                <h2>环境模板</h2>
                <div className="environment-list">
                  {environments.map((e) => (
                    <div key={e.id}>
                      <Icon name="environment" />
                      <div>
                        <strong>
                          {e.name}
                          {e.available === false && (
                            <span className="tag">本机镜像缺失</span>
                          )}
                          {e.id === user.default_environment_id && (
                            <span className="tag">我的固定环境</span>
                          )}
                          {e.recommended && <span className="tag">新用户默认 · PyTorch</span>}
                        </strong>
                        <small>{e.description}</small>
                        <code className="image-name">{e.image}</code>
                      </div>
                      <span className="tag">{e.image_version}</span>
                      {user.role === "ADMIN" && (
                        <div className="actions compact"><button
                          disabled={busy}
                          onClick={() =>
                            act(
                              () =>
                                api("/environments/" + e.id, "PATCH", {
                                  enabled: !e.enabled,
                                }),
                              "模板状态已更新",
                            )
                          }
                        >
                          {e.enabled ? "停用" : "启用"}
                        </button>
                        <button className="danger" disabled={busy}
                          onClick={() => deleteResource("/environments/" + e.id, "删除环境模板 " + e.name + "；仍被用户或记录引用的模板不能删除。保留 Docker 镜像。")}>删除模板</button></div>
                      )}
                    </div>
                  ))}
                </div>
                <p className="info">
                  Python 包安装到 /opt/user-env/venv，在 Workspace、Debug 和
                  Training 之间复用。系统 apt
                  安装随容器删除而丢失。更换镜像前需确认 Python 兼容性。
                </p>
                {user.role === "ADMIN" && (
                  <form
                    onSubmit={(e) =>
                      submit(
                        e,
                        (f) =>
                          api("/environments", "POST", {
                            name: txt(f, "name"),
                            image: txt(f, "image"),
                            image_version: txt(f, "version"),
                            description: txt(f, "description"),
                          }),
                        "已添加本地镜像模板",
                      )
                    }
                  >
                    <div className="form-grid">
                      <Field label="模板名称">
                        <input name="name" required />
                      </Field>
                      <Field label="本地镜像标签或 ID">
                        <input
                          name="image"
                          placeholder="lab-base-dev:2026.10-poc"
                          required
                        />
                      </Field>
                      <Field label="版本">
                        <input name="version" required />
                      </Field>
                      <Field label="说明">
                        <input name="description" />
                      </Field>
                    </div>
                    <button disabled={busy}>添加环境</button>
                  </form>
                )}
              </section>
              {user.role === "ADMIN" && (
                <section className="panel">
                  <h2>Docker 镜像</h2>
                  <p className="muted">仅管理员可删除未使用的镜像。先删除无引用的环境模板；集群默认镜像和容器使用中的镜像受保护。</p>
                  <div className="table-wrap"><table>
                    <thead><tr><th>镜像 / 标签</th><th>大小</th><th>使用情况</th><th>操作</th></tr></thead>
                    <tbody>{images.map((image) => <tr key={image.id}>
                      <td><strong>{image.tags.join(", ") || "无标签"}</strong><small className="mono">{image.id.slice(0, 19)}</small></td>
                      <td>{size(image.size)}</td>
                      <td>{image.blocked_reasons.join("；") || "未使用"}</td>
                      <td><button className="danger" disabled={busy || image.blocked_reasons.length > 0}
                        onClick={() => deleteResource("/admin/images/" + image.id,
                          "删除镜像 " + image.id + " 及全部标签：" + (image.tags.join(", ") || "无标签"))}>删除镜像</button></td>
                    </tr>)}</tbody>
                  </table></div>
                </section>
              )}
              <section className="panel">
                <div className="panel-head">
                  <h2>环境变量</h2>
                  {user.role === "ADMIN" && (
                    <select
                      value={scope}
                      onChange={(e) => setScope(e.target.value)}
                    >
                      <option value="global">全局</option>
                      {users.map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.username}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                <p className="info">
                  优先级：任务覆盖 &gt; 用户设置 &gt; 全局设置 &gt;
                  默认值。修改仅对新创建的容器生效。
                </p>
                <table>
                  <thead>
                    <tr>
                      <th>变量</th>
                      <th>值</th>
                      <th>类型</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {variables.map((v) => (
                      <tr key={v.scope + v.key}>
                        <td className="mono">{v.key}</td>
                        <td className="mono truncate">{v.value}</td>
                        <td>{v.is_secret ? "Secret" : "普通"}</td>
                        <td>{v.enabled ? "启用" : "停用"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <form
                  onSubmit={(e) =>
                    submit(
                      e,
                      async (f) => {
                        await api("/settings/env", "PUT", {
                          user_id:
                            user.role === "ADMIN"
                              ? scope === "global"
                                ? null
                                : scope
                              : user.id,
                          key: txt(f, "key"),
                          value: txt(f, "value"),
                          is_secret: f.get("secret") === "on",
                          enabled: f.get("enabled") === "on",
                        });
                        setVariables(
                          await api(
                            "/settings/env" +
                              (scope === "global" ? "" : "?user_id=" + scope),
                          ),
                        );
                      },
                      "变量已保存，对下次创建生效",
                    )
                  }
                >
                  <div className="form-grid">
                    <Field label="变量名">
                      <input name="key" required />
                    </Field>
                    <Field label="值">
                      <input name="value" type="password" autoComplete="off" />
                    </Field>
                  </div>
                  <div className="form-foot">
                    <div className="checks">
                      <label>
                        <input type="checkbox" name="secret" />
                        密钥
                      </label>
                      <label>
                        <input type="checkbox" name="enabled" defaultChecked />
                        启用
                      </label>
                    </div>
                    <button disabled={busy}>保存变量</button>
                  </div>
                </form>
              </section>
            </>
          )}
          {page === "storage" && (
            <section className="panel">
              <h2>持久化存储</h2>
              <p className="muted">
                文件保存在宿主机；Python 环境独立保存在每个用户的 Docker volume
                中。
              </p>
              <table>
                <thead>
                  <tr>
                    <th>用户</th>
                    <th>工作目录</th>
                    <th>结果</th>
                    <th>缓存</th>
                  </tr>
                </thead>
                <tbody>
                  {storage.map((s) => (
                    <tr key={s.username}>
                      <td>
                        <strong>{s.username}</strong>
                      </td>
                      <td>{size(s.bytes.workspace || 0)}</td>
                      <td>{size(s.bytes.results || 0)}</td>
                      <td>{size(s.bytes.scratch || 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="info">
                /datasets
                在所有用户容器中共享并只读。当前不设置硬配额；此处统计工作目录、结果和缓存，不含
                Python volume 大小。
              </p>
            </section>
          )}
          {page === "audit" && (
            <section className="panel">
              <h2>最近的操作</h2>
              <table>
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>操作</th>
                    <th>对象</th>
                    <th>详情</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.map((a) => (
                    <tr key={a.id}>
                      <td>{date(a.created_at)}</td>
                      <td>{a.action}</td>
                      <td className="mono">{a.target_id}</td>
                      <td>{auditDetail(a)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
          {page === "remote" && (
            <>
              <section className="panel remote-panel">
                <Icon name="remote" />
                <h2>Cloudflare Quick Tunnel</h2>
                <Status
                  value={
                    remote.status === "online"
                      ? "RUNNING"
                      : remote.status === "connecting"
                        ? "STARTING"
                        : "STOPPED"
                  }
                />
                {remote.url ? (
                  <>
                    <p>
                      <a href={remote.url} target="_blank" rel="noreferrer">
                        {remote.url}
                      </a>
                    </p>
                    <button
                      onClick={() =>
                        navigator.clipboard
                          .writeText(remote.url!)
                          .then(() => setNotice("链接已复制"))
                          .catch(() => setError("请手动复制链接"))
                      }
                    >
                      复制访问链接
                    </button>
                  </>
                ) : (
                  <p className="muted">
                    远程入口未启用。请联系管理员开启公网访问。
                  </p>
                )}
                <p className="info">
                  {remote.status === "connecting"
                    ? "隧道正在连接，稍后自动刷新。"
                    : "在其他网络的设备上打开上面的 HTTPS 链接，使用同一个 Portal 账号登录。"}
                  本机和 Docker
                  需要保持运行。重启隧道会更换临时地址，届时请重新复制链接。
                </p>
              </section>
              <section className="panel">
                <h2>
                  {user.role === "ADMIN"
                    ? "管理员：分配一个远程账号"
                    : "成员：开始使用"}
                </h2>
                {user.role === "ADMIN" && (
                  <>
                    <ol className="steps">
                      <li>
                        点击「用户管理」，填写用户名（例如
                        student01）、显示名称和至少 12
                        位初始密码。也可以点击「生成随机密码」。
                      </li>
                      <li>
                        角色选「成员」，固定环境选择默认 PyTorch 环境，GPU 上限填 1，Debug
                        免审批上限填 10，点击「创建用户」。
                      </li>
                      <li>
                        在新账号信息卡中点击「复制登录信息」，将链接、成员用户名和初始密码交给对应成员。
                      </li>
                    </ol>
                    <button onClick={() => setPage("users")}>
                      前往用户管理
                    </button>
                  </>
                )}
                <ol className="steps">
                  <li>
                    在另一台设备打开公网链接并登录。首次登录后，点击「我的账号」修改初始密码，再用新密码登录。
                  </li>
                  <li>
                    点击「工作区」→「启动」，等待「运行中」→「打开 VS Code」。在
                    VS Code 中点击 Terminal → New Terminal，代码放在
                    /workspace，数据从 /datasets 读取。
                  </li>
                  <li>
                    需要交互式 GPU 时，点击「在线调试」→ 选择 1 GPU 和时长
                    →「开启调试」，运行后点击「VS Code
                    ↗」。使用结束点击「停止」。
                  </li>
                  <li>
                    批量运行时，点击「训练任务」，填写运行命令和资源，点击「提交训练」。在任务列表查看状态和日志。
                  </li>
                </ol>
                <p className="info">
                  当前
                  {resources.mode === "mock-docker"
                    ? "为 mock 模式，GPU 数字用于测试排队，任务不会使用本机显卡。真实 GPU 可由管理员在本机切换到 local-gpu-docker。"
                    : "为真实 GPU 模式；工作区使用 CPU，调试和训练可申请本机 GPU。"}
                </p>
              </section>
            </>
          )}
          {page === "account" && (
            <section className="panel account-panel">
              <div className="panel-head">
                <h2>
                  {user.display_name} · {user.username}
                </h2>
                <button
                  onClick={() =>
                    api("/auth/logout", "POST")
                      .then(() => endSession())
                      .catch((e) => setError(e.message))
                  }
                >
                  退出登录
                </button>
              </div>
              <p className="muted">
                {user.role === "ADMIN" ? "管理员" : "实验室成员"} · GPU 上限{" "}
                {user.max_gpus} · Debug 免审批上限 {user.max_debug_hours} 小时；超过 10 小时可提交审批
              </p>
              <h2>修改密码</h2>
              <p className="muted">
                修改后所有设备上的登录都会失效，工作区文件和运行中的任务继续保留。
              </p>
              <form
                onSubmit={async (event) => {
                  event.preventDefault();
                  const f = new FormData(event.currentTarget);
                  if (txt(f, "new_password") !== txt(f, "confirm_password")) {
                    setError("两次输入的新密码不一致");
                    return;
                  }
                  setBusy(true);
                  setError("");
                  try {
                    await api("/auth/change-password", "POST", {
                      current_password: txt(f, "current_password"),
                      new_password: txt(f, "new_password"),
                    });
                    endSession("密码已修改，请使用新密码重新登录。");
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <div className="form-grid">
                  <Field label="当前密码">
                    <input
                      type="password"
                      name="current_password"
                      autoComplete="current-password"
                      maxLength={200}
                      required
                    />
                  </Field>
                  <Field label="新密码 (至少 12 位)">
                    <input
                      type="password"
                      name="new_password"
                      autoComplete="new-password"
                      minLength={12}
                      maxLength={200}
                      required
                    />
                  </Field>
                  <Field label="确认新密码">
                    <input
                      type="password"
                      name="confirm_password"
                      autoComplete="new-password"
                      minLength={12}
                      maxLength={200}
                      required
                    />
                  </Field>
                </div>
                <button className="primary" disabled={busy}>
                  修改密码并重新登录
                </button>
              </form>
            </section>
          )}
          <footer>
            GPU LAB · Ubuntu Docker
            <span>{activeDebug.length} 个活跃调试会话</span>
          </footer>
        </main>
      </div>
      {logTarget && (
        <div className="modal-backdrop" onClick={() => setLogTarget(null)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="任务日志"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="panel-head">
              <h2>运行日志 · {logTarget.id.slice(0, 8)}</h2>
              <button onClick={() => setLogTarget(null)}>关闭 ×</button>
            </div>
            <pre>{log}</pre>
          </section>
        </div>
      )}
    </div>
  );
}
function Empty({ text }: { text: string }) {
  return (
    <div className="empty">
      <span>◇</span>
      <p>{text}</p>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
