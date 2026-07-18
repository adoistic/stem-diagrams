# STEM Diagrams — gated viewer (Cloudflare Worker)

Members-only viewer for the diagram library. All auth runs natively on the
Worker — no Firebase, no third-party identity.

**Live:** https://stem-diagrams-viewer.appsadoistic.workers.dev

## What it does
- **Register / log in** with email + password. Passwords hashed with PBKDF2
  (Web Crypto); sessions are HMAC-signed cookies (30 days).
- **Gated** — the gallery, the image bytes (`/img/...`), and downloads all
  require a valid session.
- **Download all** — streams a zip of only the images you *haven't* downloaded
  yet, in 200-image chunks (concurrent R2 reads). Downloaded images are logged
  per-user in D1, so the next click only fetches what's new.

## Stack
- Cloudflare Worker (`src/index.js`), frontend inlined (`src/app.js`)
- **R2** bucket `stem-diagrams-dataset` (reads `v3/gallery/data.json` as the
  manifest + serves `v3/img/...`)
- **D1** `stem-diagrams-downloads`: `users` (uid,email,salt,hash) +
  `downloads` (uid,image,ts)
- `fflate` for zipping

## Deploy
```bash
npm install
npx wrangler d1 execute stem-diagrams-downloads --remote --file migrations/0001_init.sql
npx wrangler deploy
```
