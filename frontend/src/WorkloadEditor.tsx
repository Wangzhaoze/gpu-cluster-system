import React from "react";
import type { Workload } from "./types";

export function WorkloadEditor({ item, busy, save, close }: {
  item: Workload; busy: boolean; save: (data: Record<string, unknown>) => void; close: () => void;
}) {
  const running = item.status === "RUNNING";
  return <div className="modal-backdrop"><section className="modal workload-editor" role="dialog" aria-modal="true" aria-labelledby="workload-edit-title">
    <div className="panel-head"><h2 id="workload-edit-title">编辑{item.kind === "debug" ? "调试" : "训练"} · {item.username}</h2><button onClick={close} disabled={busy}>关闭</button></div>
    <form onSubmit={event => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const data: Record<string, unknown> = { time_limit_seconds: Number(form.get("time")) };
      if (!running) {
        const indices = String(form.get("indices") || "").trim();
        Object.assign(data, { requested_gpus: Number(form.get("gpus")), requested_cpus: Number(form.get("cpus")), requested_ram_mb: Number(form.get("ram")), gpu_indices: indices ? indices.split(",").map(s => Number(s.trim())) : null });
        if (item.kind === "train") Object.assign(data, { command: form.get("command"), workdir: form.get("workdir"), output_name: form.get("output") });
      }
      save(data);
    }}>
      <div className="form-grid">
        <label className="field"><span>总时长（秒）</span><input name="time" type="number" min="5" max="604800" defaultValue={item.time_limit_seconds} required /></label>
        {!running && <>
          <label className="field"><span>GPU 数量</span><input name="gpus" type="number" min="0" max={item.kind === "debug" ? 1 : 64} defaultValue={item.requested_gpus} required /></label>
          <label className="field"><span>显卡编号（逗号分隔，空白为自动）</span><input name="indices" defaultValue={item.requested_gpu_indices?.join(",") || ""} pattern="[0-9, ]*" /></label>
          <label className="field"><span>CPU 核数</span><input name="cpus" type="number" min="1" max="32" defaultValue={item.requested_cpus} required /></label>
          <label className="field"><span>内存（MB）</span><input name="ram" type="number" min="256" max="65536" defaultValue={item.requested_ram_mb} required /></label>
          {item.kind === "train" && <>
            <label className="field"><span>工作目录</span><input name="workdir" defaultValue={item.workdir} required /></label>
            <label className="field"><span>输出名称</span><input name="output" defaultValue={item.output_name} pattern="[A-Za-z0-9_-]{1,80}" required /></label>
          </>}
        </>}
      </div>
      {!running && item.kind === "train" && <label className="field"><span>运行命令</span><textarea name="command" defaultValue={item.command} rows={3} required /></label>}
      <div className="actions"><button className="primary" disabled={busy}>保存修改</button></div>
    </form>
  </section></div>;
}
