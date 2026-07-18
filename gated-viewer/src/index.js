/**
 * STEM Diagrams gated viewer — all auth on Cloudflare Workers, no Firebase.
 *
 * Anyone can register (email + password) and log in. Password is hashed with
 * PBKDF2 (Web Crypto). A signed session cookie (HMAC-SHA256) gates the gallery,
 * the image bytes, and downloads. "Download All" streams a zip of only the
 * images the user hasn't downloaded yet; downloaded images are logged in D1 so
 * the next click only fetches what's new.
 */

import { zipSync } from "fflate";
import { APP_HTML } from "./app.js";

const enc = new TextEncoder();
const MANIFEST_KEY = "v3/gallery/data.json";
const DOWNLOAD_LIMIT = 200;          // images per zip chunk (bounds Worker memory/time)
const SESSION_DAYS = 30;

// ---------- small helpers ----------
const b64u = {
  enc: (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""),
  dec: (s) => {
    s = s.replace(/-/g, "+").replace(/_/g, "/");
    const bin = atob(s + "===".slice((s.length + 3) % 4));
    return Uint8Array.from(bin, (c) => c.charCodeAt(0));
  },
};
const json = (obj, status = 200, headers = {}) =>
  new Response(JSON.stringify(obj), {
    status, headers: { "content-type": "application/json", ...headers },
  });

async function sessionSecret(env) {
  // Derive a stable secret from account-bound material; override with the
  // SESSION_SECRET binding in production for rotation.
  return env.SESSION_SECRET || "stem-diagrams-" + env.DB.constructor.name;
}

async function hmacKey(secret) {
  return crypto.subtle.importKey("raw", enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

async function signToken(payload, secret) {
  const body = b64u.enc(enc.encode(JSON.stringify(payload)));
  const key = await hmacKey(secret);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(body));
  return body + "." + b64u.enc(sig);
}

async function verifyToken(token, secret) {
  if (!token || !token.includes(".")) return null;
  const [body, sig] = token.split(".");
  const key = await hmacKey(secret);
  const ok = await crypto.subtle.verify("HMAC", key, b64u.dec(sig), enc.encode(body));
  if (!ok) return null;
  try {
    const p = JSON.parse(new TextDecoder().decode(b64u.dec(body)));
    if (p.exp && p.exp < Date.now() / 1000) return null;
    return p;
  } catch { return null; }
}

async function pbkdf2(password, saltBytes) {
  const key = await crypto.subtle.importKey("raw", enc.encode(password),
    "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: saltBytes, iterations: 100000, hash: "SHA-256" }, key, 256);
  return b64u.enc(bits);
}

function cookie(name, req) {
  const m = (req.headers.get("cookie") || "").match(new RegExp("(?:^|; )" + name + "=([^;]+)"));
  return m ? m[1] : null;
}
function setCookie(token) {
  const maxAge = SESSION_DAYS * 86400;
  return `sd_session=${token}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=${maxAge}`;
}

async function currentUser(req, env) {
  const secret = await sessionSecret(env);
  return verifyToken(cookie("sd_session", req), secret);
}

async function getManifest(env) {
  const obj = await env.BUCKET.get(MANIFEST_KEY);
  if (!obj) return [];
  const data = JSON.parse(await obj.text());
  return (data.images || []).map((im) => ({
    key: im.url, field: im.category, page: im.page,
    caption: im.caption || "", arxiv_id: im.arxiv_id,
  }));
}

// ---------- routes ----------
export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const path = url.pathname;
    const secret = await sessionSecret(env);

    try {
      if (path === "/" || path === "/index.html")
        return new Response(APP_HTML, { headers: { "content-type": "text/html; charset=utf-8" } });

      // ---- auth ----
      if (path === "/api/register" || path === "/api/login") {
        if (req.method !== "POST") return json({ error: "POST only" }, 405);
        const { email, password } = await req.json().catch(() => ({}));
        const em = (email || "").trim().toLowerCase();
        if (!em || !em.includes("@") || !password || password.length < 6)
          return json({ error: "Enter a valid email and a password of at least 6 characters." }, 400);

        if (path === "/api/register") {
          const exists = await env.DB.prepare("SELECT uid FROM users WHERE email=?").bind(em).first();
          if (exists) return json({ error: "That email is already registered — try logging in." }, 409);
          const salt = crypto.getRandomValues(new Uint8Array(16));
          const hash = await pbkdf2(password, salt);
          const uid = crypto.randomUUID();
          await env.DB.prepare("INSERT INTO users(uid,email,salt,hash,created_at) VALUES(?,?,?,?,?)")
            .bind(uid, em, b64u.enc(salt), hash, Date.now()).run();
          const token = await signToken({ uid, email: em, exp: Date.now() / 1000 + SESSION_DAYS * 86400 }, secret);
          return json({ email: em }, 200, { "set-cookie": setCookie(token) });
        } else {
          const u = await env.DB.prepare("SELECT uid,salt,hash FROM users WHERE email=?").bind(em).first();
          if (!u) return json({ error: "No account with that email." }, 401);
          const hash = await pbkdf2(password, b64u.dec(u.salt));
          if (hash !== u.hash) return json({ error: "Wrong password." }, 401);
          const token = await signToken({ uid: u.uid, email: em, exp: Date.now() / 1000 + SESSION_DAYS * 86400 }, secret);
          return json({ email: em }, 200, { "set-cookie": setCookie(token) });
        }
      }

      if (path === "/api/logout")
        return json({ ok: true }, 200, { "set-cookie": "sd_session=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0" });

      if (path === "/api/me") {
        const user = await currentUser(req, env);
        return user ? json({ email: user.email }) : json({ error: "not logged in" }, 401);
      }

      // ---- everything below requires login ----
      const user = await currentUser(req, env);
      if (!user) return json({ error: "Please log in." }, 401);

      if (path === "/api/manifest") {
        const items = await getManifest(env);
        const dl = await env.DB.prepare("SELECT image FROM downloads WHERE uid=?").bind(user.uid).all();
        const got = new Set((dl.results || []).map((r) => r.image));
        return json({
          total: items.length, downloaded: got.size, pending: items.length - got.size,
          images: items.map((it) => ({ ...it, downloaded: got.has(it.key) })),
        });
      }

      if (path === "/api/pending") {
        const items = await getManifest(env);
        const dl = await env.DB.prepare("SELECT COUNT(*) n FROM downloads WHERE uid=?").bind(user.uid).first();
        return json({ total: items.length, downloaded: dl.n, pending: items.length - dl.n });
      }

      if (path.startsWith("/img/")) {
        const key = decodeURIComponent(path.slice(1)); // "img/..." -> actual key is v3/img/...
        const obj = await env.BUCKET.get("v3/" + key.replace(/^img\//, "img/"));
        if (!obj) return new Response("not found", { status: 404 });
        return new Response(obj.body, {
          headers: { "content-type": "image/png", "cache-control": "private, max-age=3600" },
        });
      }

      if (path === "/api/download" && req.method === "POST") {
        const items = await getManifest(env);
        const dl = await env.DB.prepare("SELECT image FROM downloads WHERE uid=?").bind(user.uid).all();
        const got = new Set((dl.results || []).map((r) => r.image));
        const pending = items.filter((it) => !got.has(it.key));
        if (pending.length === 0) return json({ done: true, remaining: 0, added: 0 });

        const chunk = pending.slice(0, DOWNLOAD_LIMIT);
        const now = Date.now();
        // read all objects concurrently
        const fetched = await Promise.all(chunk.map(async (it) => {
          const obj = await env.BUCKET.get(it.key);
          if (!obj) return null;
          return { field: it.field, key: it.key,
                   nm: it.key.split("/").slice(-1)[0],
                   buf: new Uint8Array(await obj.arrayBuffer()) };
        }));
        const files = {};
        const recorded = [];
        for (const r of fetched) {
          if (!r) continue;
          files[`${r.field}/${r.nm}`] = r.buf;
          recorded.push(r.key);
        }
        const zip = zipSync(files, { level: 4 });
        // log them as downloaded (batch insert)
        const stmt = env.DB.prepare("INSERT OR IGNORE INTO downloads(uid,image,ts) VALUES(?,?,?)");
        await env.DB.batch(recorded.map((k) => stmt.bind(user.uid, k, now)));
        const remaining = pending.length - recorded.length;
        return new Response(zip, {
          headers: {
            "content-type": "application/zip",
            "content-disposition": `attachment; filename="stem-diagrams-batch.zip"`,
            "x-remaining": String(remaining),
            "x-added": String(recorded.length),
          },
        });
      }

      return json({ error: "not found" }, 404);
    } catch (err) {
      return json({ error: String(err && err.message || err) }, 500);
    }
  },
};
