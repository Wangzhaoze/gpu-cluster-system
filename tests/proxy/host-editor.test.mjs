import assert from "node:assert/strict";
import http from "node:http";
import net from "node:net";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import test from "node:test";
import { createProxy } from "../../infra/host-editor-proxy.mjs";

async function listen(server, endpoint) {
  await new Promise(resolve => server.listen(endpoint, resolve));
  return server.address();
}

test("native host gateway enforces admin authorization for HTTP and upgrades", async (t) => {
  const directory = await mkdtemp(tmpdir() + "/host-proxy-");
  const socketPath = directory + "/editor.sock";
  let hits = 0;
  const native = http.createServer((req, res) => { hits++; res.end("HOST_NATIVE"); });
  native.on("upgrade", (req, socket, head) => {
    hits++;
    socket.on("error", () => {});
    socket.write("HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\nSERVER_HEAD");
    if (head.length) socket.write(head);
    socket.on("data", data => socket.write(data));
    socket.on("end", () => socket.end());
  });
  await listen(native, socketPath);
  const auth = http.createServer((req, res) => {
    res.writeHead(req.headers.cookie === "lab_session=admin" ? 204 : (req.headers.cookie ? 403 : 401)); res.end();
  });
  const authAddress = await listen(auth, { host: "127.0.0.1", port: 0 });
  const proxy = createProxy({ socketPath, authUrl: `http://127.0.0.1:${authAddress.port}/auth` });
  const address = await listen(proxy, { host: "127.0.0.1", port: 0 });
  const base = `http://127.0.0.1:${address.port}`;
  t.after(async () => {
    for (const server of [proxy, auth, native]) { server.closeAllConnections(); await new Promise(r => server.close(r)); }
    await rm(directory, { recursive: true });
  });
  await t.test("anonymous and direct student HTTP denied before host is contacted", async () => {
    assert.equal((await fetch(base)).status, 401);
    assert.equal((await fetch(base, { headers: { Cookie: "lab_session=student" } })).status, 403);
    assert.equal(hits, 0);
  });
  await t.test("admin HTTP reaches native editor", async () => {
    const response = await fetch(base + "/files", { headers: { Cookie: "lab_session=admin" } });
    assert.equal(response.status, 200); assert.equal(await response.text(), "HOST_NATIVE");
  });
  await t.test("cross-origin and cross-site mutations denied", async () => {
    const before = hits;
    assert.equal((await fetch(base, { method: "POST", headers: { Cookie: "lab_session=admin", Origin: "https://attacker.invalid" } })).status, 403);
    assert.equal((await fetch(base, { method: "POST", headers: { Cookie: "lab_session=admin", "Sec-Fetch-Site": "cross-site" } })).status, 403);
    assert.equal(hits, before);
  });
  async function upgrade(cookie = "", origin = base) {
    return new Promise((resolve, reject) => {
      const socket = net.connect(address.port, "127.0.0.1");
      let data = "";
      socket.setTimeout(3000, () => { socket.destroy(); reject(new Error("upgrade timeout")); });
      socket.on("error", reject);
      socket.on("connect", () => socket.write(`GET / HTTP/1.1\r\nHost: 127.0.0.1:${address.port}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nCookie: ${cookie}\r\nOrigin: ${origin}\r\n\r\nCLIENT_HEAD`));
      socket.on("data", chunk => {
        data += chunk;
        if (/HTTP\/1.1 (401|403)/.test(data) || (data.includes("SERVER_HEAD") && data.includes("CLIENT_HEAD"))) { socket.destroy(); resolve(data); }
      });
    });
  }
  await t.test("guest, student and cross-origin WebSockets denied", async () => {
    const before = hits;
    assert.match(await upgrade(), /^HTTP\/1.1 401/);
    assert.match(await upgrade("lab_session=student"), /^HTTP\/1.1 403/);
    assert.match(await upgrade("lab_session=admin", "https://attacker.invalid"), /^HTTP\/1.1 403/);
    assert.equal(hits, before);
  });
  await t.test("admin WebSocket upgrade preserves data in both directions", async () => {
    assert.match(await upgrade("lab_session=admin"), /^HTTP\/1.1 101/);
  });
  await t.test("auth service outage fails closed", async () => {
    auth.closeAllConnections(); await new Promise(resolve => auth.close(resolve));
    assert.equal((await fetch(base, { headers: { Cookie: "lab_session=admin" } })).status, 503);
  });
});
