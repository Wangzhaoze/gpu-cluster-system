import React, { useEffect, useState } from "react";
import type { Announcement } from "./types";

export function AdminAnnouncements({ items, save, publish }: {
  items: Announcement[];
  save: (title: string, body: string, id?: string) => Promise<void>;
  publish: (id: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState<string | undefined>();
  const [title, setTitle] = useState(""), [body, setBody] = useState("");
  const [preview, setPreview] = useState<Announcement | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function perform(action: () => Promise<void>) {
    setError(""); setBusy(true);
    try { await action(); } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <>
    <section className="panel">
      <h2>{editing ? "编辑公告草稿" : "新增公告"}</h2>
      {error && !preview && <p role="alert" className="alert error">{error}</p>}
      <form onSubmit={e => {
        e.preventDefault();
        perform(async () => { await save(title, body, editing); setEditing(undefined); setTitle(""); setBody(""); });
      }}>
        <label className="field"><span>公告标题</span><input value={title} onChange={e => setTitle(e.target.value)} maxLength={200} required /></label>
        <label className="field"><span>公告内容</span><textarea value={body} onChange={e => setBody(e.target.value)} rows={8} maxLength={20000} required /></label>
        <div className="actions"><button className="primary" disabled={busy}>保存草稿</button>
          {editing && <button type="button" disabled={busy} onClick={() => { setEditing(undefined); setTitle(""); setBody(""); }}>取消编辑</button>}
        </div>
      </form>
    </section>
    <section className="panel"><h2>公告列表</h2>
      {!items.length && <p className="muted">还没有公告。</p>}
      {items.map(item => <article className="announcement-row" key={item.id}>
        <div className="panel-head"><strong>{item.title}</strong><span className="tag">{item.published_at ? "已发布" : "草稿"}</span></div>
        <details><summary>查看内容</summary><p className="announcement-body">{item.body}</p></details>
        <div className="actions">
          {!item.published_at && <>
            <button disabled={busy} onClick={() => { setEditing(item.id); setTitle(item.title); setBody(item.body); }}>编辑草稿</button>
            <button disabled={busy} onClick={() => { setError(""); setPreview(item); }}>预览并发布</button>
          </>}
          {item.published_at && <small className="muted">发布于 {new Date(item.published_at).toLocaleString("zh-CN")}</small>}
        </div>
      </article>)}
    </section>
    {preview && <div className="modal-backdrop announcement-backdrop"><section className="modal announcement-modal" role="dialog" aria-modal="true" aria-labelledby="announcement-preview-title">
      <h2 id="announcement-preview-title">确认发布：{preview.title}</h2>
      <p className="announcement-body">{preview.body}</p>
      <p className="muted">发布后，成员在线时或下次登录时会收到公告。已发布的内容不可修改。</p>
      {error && <p role="alert" className="alert error">{error}</p>}
      <div className="actions"><button disabled={busy} onClick={() => setPreview(null)}>返回</button>
        <button className="primary" disabled={busy} onClick={() => perform(async () => { await publish(preview.id); setPreview(null); })}>确认发布</button>
      </div>
    </section></div>}
  </>;
}

export function MemberAnnouncement({ item, acknowledge }: { item: Announcement; acknowledge: () => Promise<void> }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => { setError(""); }, [item.id]);
  return <div className="modal-backdrop announcement-backdrop"><section className="modal announcement-modal" role="dialog" aria-modal="true" aria-labelledby="member-announcement-title">
    <h2 id="member-announcement-title">公告 · {item.title}</h2>
    <p className="announcement-body">{item.body}</p>
    {error && <p role="alert" className="alert error">{error}</p>}
    <div className="actions"><button className="primary" autoFocus disabled={busy} onClick={async () => {
      setError(""); setBusy(true);
      try { await acknowledge(); } catch (e) { setError((e as Error).message); setBusy(false); }
    }}>关闭</button><small className="muted">关闭后标记为已读</small></div>
  </section></div>;
}
