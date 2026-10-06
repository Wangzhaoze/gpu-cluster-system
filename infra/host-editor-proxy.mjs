// The editor itself runs on Ubuntu. This gateway mounts only its private socket.
import http from "node:http";
import { pathToFileURL } from "node:url";

export function createProxy({ socketPath, authUrl }) {
  function deny(res, status) {
    res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
    res.end(JSON.stringify({ detail: status === 503 ? "宿主机服务暂不可用" : "需要管理员登录" }));
  }
  function authorize(req) {
    const authority = String(req.headers["x-forwarded-host"] || req.headers.host || "").split(",")[0].trim();
    try {
      if (req.headers.origin && new URL(req.headers.origin).host !== authority) return Promise.resolve(403);
    } catch { return Promise.resolve(403); }
    if ((req.headers.upgrade || !["GET", "HEAD", "OPTIONS"].includes(req.method)) && req.headers["sec-fetch-site"] === "cross-site") return Promise.resolve(403);
    return new Promise((resolve) => {
      const check = http.get(authUrl, { headers: { Cookie: req.headers.cookie || "" }, timeout: 5000 }, (response) => {
        response.resume();
        resolve(response.statusCode === 204 ? 204 : ([401, 403].includes(response.statusCode) ? response.statusCode : 503));
      });
      check.on("timeout", () => check.destroy());
      check.on("error", () => resolve(503));
    });
  }
  const server = http.createServer(async (req, res) => {
    if (req.method === "GET" && req.url === "/healthz") {
      const health = http.get({ socketPath, path: "/healthz", timeout: 2000 }, (response) => {
        response.resume();
        if (response.statusCode !== 200) return deny(res, 503);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end('{"status":"ok"}');
      });
      health.on("timeout", () => health.destroy());
      health.on("error", () => { if (!res.headersSent) deny(res, 503); });
      return;
    }
    const status = await authorize(req);
    if (status !== 204) return deny(res, status);
    const upstream = http.request({ socketPath, path: req.url, method: req.method, headers: req.headers }, (response) => {
      res.writeHead(response.statusCode, response.headers);
      response.pipe(res);
    });
    upstream.on("error", () => { if (!res.headersSent) deny(res, 503); else res.destroy(); });
    req.on("aborted", () => upstream.destroy());
    req.pipe(upstream);
  });
  server.on("upgrade", async (req, socket, head) => {
    socket.on("error", () => socket.destroy());
    const status = await authorize(req);
    if (socket.destroyed) return;
    if (status !== 204) return socket.end(`HTTP/1.1 ${status} Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
    const upstream = http.request({ socketPath, path: req.url, method: "GET", headers: req.headers });
    upstream.on("upgrade", (response, peer, peerHead) => {
      const headers = Object.entries(response.headers).flatMap(([key, value]) => (Array.isArray(value) ? value : [value]).map(v => `${key}: ${v}`));
      socket.write(`HTTP/1.1 101 Switching Protocols\r\n${headers.join("\r\n")}\r\n\r\n`);
      if (peerHead.length) socket.write(peerHead);
      if (head.length) peer.write(head);
      peer.on("error", () => socket.destroy());
      peer.on("close", () => socket.destroy());
      socket.on("close", () => peer.destroy());
      socket.on("end", () => peer.destroy());
      peer.pipe(socket); socket.pipe(peer);
    });
    upstream.on("response", (response) => {
      response.resume();
      socket.end(`HTTP/1.1 ${response.statusCode} Upstream Error\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
    });
    upstream.on("error", () => { if (!socket.destroyed) socket.end("HTTP/1.1 503 Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"); });
    upstream.end();
  });
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  createProxy({ socketPath: process.env.HOST_EDITOR_SOCKET || "/run/host-editor/editor.sock", authUrl: process.env.HOST_EDITOR_AUTH_URL || "http://backend:8000/api/auth/host-editor" }).listen(8080, "0.0.0.0");
}
