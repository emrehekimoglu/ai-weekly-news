/**
 * AI & Teknoloji Radarı: e-postadaki bağlantıların açıldığı sayfa.
 *
 * Eski Apps Script web uygulamasının (doGet) yerini alır; aynı adres biçimini kabul eder:
 *   ?action=confirm&email=…&token=…      abonelik onayı (C sütunu → AKTIF)
 *   ?action=unsubscribe&email=…&token=…  abonelikten çıkma (C sütunu → IPTAL)
 *   ?action=vote&issue=…&story=…&v=…&voter=…  👍/👎 oyu ("Geri Bildirim" sayfası)
 *
 * Abone tablosu Google Sheets API ile, servis hesabı (GCP_SA_KEY) üzerinden okunup yazılır;
 * tablo bu hesapla "Düzenleyen" olarak paylaşılmış olmalı. Okurun Google hesabıyla hiçbir ilgisi
 * yoktur; bu yüzden birden fazla Google hesabı açık tarayıcılarda da çalışır.
 */

const SHEETS = "https://sheets.googleapis.com/v4/spreadsheets";
const SCOPE = "https://www.googleapis.com/auth/spreadsheets";
const FEEDBACK_SHEET = "Geri Bildirim";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/") return page(404, "🤔", "Sayfa bulunamadı", "");
    const p = Object.fromEntries(url.searchParams);
    try {
      const sheets = new Sheets(env);
      if (p.action === "vote") return await vote(sheets, p);
      if (p.action === "confirm" || p.action === "unsubscribe") return await subscription(sheets, p);
      return page(400, "🤔", "Geçersiz istek", "Bu bağlantı tanınmadı.");
    } catch (err) {
      console.error(err);
      // Hatanın kısa özeti sayfada görünür ki kurulum sorunları (ör. tablo izni) hemen anlaşılsın
      return page(500, "⚠️", "Bir hata oluştu", `Lütfen biraz sonra tekrar deneyin. (${errorSummary(err)})`);
    }
  },
};

async function subscription(sheets, p) {
  const email = (p.email || "").trim().toLowerCase();
  const token = (p.token || "").trim();
  if (!email || !token) return page(400, "🤔", "Geçersiz veya eksik istek", "Bağlantı eksik görünüyor.");

  // İlk sayfa (Form yanıtları): A zaman, B e-posta, C durum, D token
  const rows = await sheets.get("A:D");
  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    if (String(row[1] || "").trim().toLowerCase() === email && String(row[3] || "").trim() === token) {
      if (p.action === "confirm") {
        await sheets.put(`C${i + 1}`, [["AKTIF"]]);
        return page(200, "✓", "Aboneliğiniz Onaylandı!",
                    "Her Pazartesi sabahı güncel AI gelişmelerini gelen kutunuzda bulacaksınız.", "#16a34a");
      }
      await sheets.put(`C${i + 1}`, [["IPTAL"]]);
      return page(200, "👋", "Abonelikten Ayrıldınız",
                  "E-posta adresiniz listeden çıkarıldı. Artık bülten almayacaksınız.", "#dc2626");
    }
  }
  return page(404, "🤔", "Kayıt bulunamadı", "Eşleşen kayıt bulunamadı veya bağlantı geçersiz.");
}

/** Sadece beklenen biçimdeki oy değerlerini kabul eder; aksi halde null. */
export function cleanVote(p) {
  const issue = String(p.issue || "");
  const story = String(p.story || "");
  const v = String(p.v || "");
  const voter = String(p.voter || "");
  if (!/^(onizleme-)?\d{4}-\d{2}-\d{2}$/.test(issue)) return null;
  if (!/^\d{1,2}$/.test(story)) return null;
  if (v !== "up" && v !== "down") return null;
  if (!/^[0-9a-f]{0,16}$/.test(voter)) return null;
  return { issue, story: Number(story), v, voter };
}

async function vote(sheets, p) {
  const vote = cleanVote(p);
  if (!vote) return page(400, "🤔", "Bağlantı geçersiz", "Bu oy bağlantısı tanınmadı.");

  const range = `'${FEEDBACK_SHEET}'!A:E`;
  let rows = await sheets.get(range).catch(() => null);
  if (rows === null) {
    await sheets.addSheet(FEEDBACK_SHEET);
    await sheets.append(range, [["Zaman", "Sayı", "Haber", "Oy", "Okur"]]);
    rows = [];
  }
  const row = [new Date().toISOString().slice(0, 19).replace("T", " "), vote.issue, vote.story, vote.v,
               vote.voter || "anonim"];
  // Aynı okur aynı habere tekrar oy verirse eski satırı günceller
  const i = vote.voter ? rows.findIndex((r, n) => n > 0 && String(r[1]) === vote.issue
                                         && Number(r[2]) === vote.story && String(r[4]) === vote.voter) : -1;
  if (i > 0) await sheets.put(`'${FEEDBACK_SHEET}'!A${i + 1}:E${i + 1}`, [row]);
  else await sheets.append(range, [row]);

  return page(200, vote.v === "up" ? "👍" : "👎", "Teşekkürler!",
              "Oyunuz kaydedildi. Fikrinizi değiştirirseniz diğer bağlantıya tıklamanız yeterli.");
}

/** Hata özeti: Google'ın kısa hata mesajı; tablo kimliği veya istek içeriği gösterilmez. */
export function errorSummary(err) {
  const m = String(err && err.message || err).match(/^(Sheets API \d+|Google jetonu alınamadı: \d+)(?::\s*(.*))?$/s);
  if (!m) return `${err && err.name || "Hata"}: ${String(err && err.message || "").slice(0, 160)}`;
  let detail = "";
  try { detail = JSON.parse(m[2]).error.message; } catch { /* gövde JSON değil */ }
  return detail ? `${m[1]}: ${detail.slice(0, 160)}` : m[1];
}

/** Google Sheets API: servis hesabı JWT'si ile erişim jetonu alır ve değerleri okur/yazar. */
export class Sheets {
  constructor(env, fetchFn) {
    this.key = JSON.parse(env.GCP_SA_KEY);
    this.id = env.SPREADSHEET_ID;
    // Workers'ta fetch başka bir nesneye bağlı çağrılırsa "Illegal invocation" (TypeError) verir
    this.fetch = fetchFn || ((...args) => fetch(...args));
  }

  async token() {
    if (this._token && this._expires > Date.now()) return this._token;
    const now = Math.floor(Date.now() / 1000);
    const claims = { iss: this.key.client_email, scope: SCOPE, aud: "https://oauth2.googleapis.com/token",
                     iat: now, exp: now + 3600 };
    const assertion = await signJwt(claims, this.key.private_key);
    const res = await this.fetch("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer", assertion }),
    });
    if (!res.ok) throw new Error(`Google jetonu alınamadı: ${res.status}: ${await res.text()}`);
    this._token = (await res.json()).access_token;
    this._expires = Date.now() + 50 * 60 * 1000;
    return this._token;
  }

  async call(path, options = {}) {
    const res = await this.fetch(`${SHEETS}/${this.id}${path}`, {
      ...options,
      headers: { authorization: `Bearer ${await this.token()}`, "content-type": "application/json" },
    });
    if (!res.ok) throw new Error(`Sheets API ${res.status}: ${await res.text()}`);
    return res.json();
  }

  async get(range) {
    return (await this.call(`/values/${encodeURIComponent(range)}`)).values || [];
  }

  put(range, values) {
    return this.call(`/values/${encodeURIComponent(range)}?valueInputOption=RAW`,
                     { method: "PUT", body: JSON.stringify({ values }) });
  }

  append(range, values) {
    return this.call(`/values/${encodeURIComponent(range)}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS`,
                     { method: "POST", body: JSON.stringify({ values }) });
  }

  addSheet(title) {
    return this.call(":batchUpdate", { method: "POST",
      body: JSON.stringify({ requests: [{ addSheet: { properties: { title } } }] }) });
  }
}

const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes)))
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function signJwt(claims, pem) {
  const enc = (obj) => b64url(new TextEncoder().encode(JSON.stringify(obj)));
  const input = `${enc({ alg: "RS256", typ: "JWT" })}.${enc(claims)}`;
  const der = Uint8Array.from(atob(pem.replace(/-----[^-]+-----|\s/g, "")), (c) => c.charCodeAt(0));
  const key = await crypto.subtle.importKey("pkcs8", der, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
                                            false, ["sign"]);
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(input));
  return `${input}.${b64url(sig)}`;
}

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function page(status, icon, title, text, color = "#10141c") {
  const html = `<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>AI &amp; Teknoloji Radarı</title>
<style>body{margin:0;padding:48px 20px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:#eceff4;color:#10141c;text-align:center}.card{max-width:440px;margin:0 auto;background:#fff;
border:1px solid #dfe3ea;padding:32px 24px}.big{font-size:44px}h1{font:700 24px Georgia,serif;margin:12px 0 8px}
p{color:#454d5c;line-height:1.5;margin:0}.brand{font:700 12px sans-serif;letter-spacing:2px;margin-bottom:24px}</style>
</head><body><div class="brand">AI &amp; TEKNOLOJİ RADARI</div><div class="card"><div class="big">${esc(icon)}</div>
<h1 style="color:${color}">${esc(title)}</h1><p>${esc(text)}</p></div></body></html>`;
  return new Response(html, { status, headers: { "content-type": "text/html; charset=utf-8",
                                                  "cache-control": "no-store" } });
}
