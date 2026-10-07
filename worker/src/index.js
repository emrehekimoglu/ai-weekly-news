/**
 * AI & Teknoloji Radarı: e-postadaki bağlantıların açıldığı sayfa.
 *
 * Eski Apps Script web uygulamasının (doGet) yerini alır; aynı adres biçimini kabul eder:
 *   ?action=confirm&email=…&token=…      abonelik onayı (C sütunu → AKTIF)
 *   ?action=unsubscribe&email=…&token=…  abonelikten çıkma (C sütunu → IPTAL)
 *   ?action=vote&issue=…&story=…&v=…&voter=…  👍/👎 oyu ("Geri Bildirim" sayfası)
 *
 * Oy ve iptal bağlantıları GET ile hiçbir şey değiştirmez: kendini POST ile gönderen bir sayfa döner.
 * E-postadaki bağlantıları tarayan güvenlik/spam botları (mail-tester, Outlook Safe Links…) JavaScript
 * çalıştırmadığı için oy veremez, kimseyi abonelikten çıkaramaz; okur ise farkı görmez.
 * Gmail'in tek tıkla iptal düğmesi (RFC 8058) zaten doğrudan POST atar.
 *
 * Ayrıca bültenin kendi abonelik sayfası: GET /abone formu gösterir, POST /abone tabloya BEKLIYOR satırı
 * ekleyip Gmail üzerinden onay e-postası gönderir (çift onay; Google Formu'na gerek kalmaz).
 *
 * Abone tablosu Google Sheets API ile, servis hesabı (GCP_SA_KEY) üzerinden okunup yazılır;
 * tablo bu hesapla "Düzenleyen" olarak paylaşılmış olmalı. Okurun Google hesabıyla hiçbir ilgisi
 * yoktur; bu yüzden birden fazla Google hesabı açık tarayıcılarda da çalışır.
 */

import { sendMail } from "./smtp.js";

const SHEETS = "https://sheets.googleapis.com/v4/spreadsheets";
const SCOPE = "https://www.googleapis.com/auth/spreadsheets";
const FEEDBACK_SHEET = "Geri Bildirim";
const SIGNUP_COOLDOWN_MS = 10 * 60 * 1000;  // aynı adrese 10 dakikada en fazla bir onay e-postası
const SIGNUPS_PER_DAY = 50;  // Gmail'in günlük gönderim sınırı bültene kalsın diye

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = Object.fromEntries(url.searchParams);
    const isSignup = url.pathname === "/abone" || url.pathname === "/abone/";
    if (!isSignup && url.pathname !== "/") return page(404, "🤔", "Sayfa bulunamadı", "");
    if (request.method === "GET" && (isSignup || !p.action)) return signupPage(env);
    if (!isSignup && request.method !== "POST" && (p.action === "vote" || p.action === "unsubscribe")) {
      const ok = p.action === "vote" ? cleanVote(p) : p.email && p.token;
      return ok ? selfPost() : page(400, "🤔", "Bağlantı geçersiz", "Bu bağlantı tanınmadı.");
    }
    try {
      const sheets = new Sheets(env);
      if (isSignup && request.method === "POST") return await signup(sheets, env, request, url);
      if (p.action === "vote") return await vote(sheets, p);
      if (p.action === "confirm" || p.action === "unsubscribe") return await subscription(sheets, p, env);
      return page(400, "🤔", "Geçersiz istek", "Bu bağlantı tanınmadı.");
    } catch (err) {
      console.error(err);
      // Hatanın kısa özeti sayfada görünür ki kurulum sorunları (ör. tablo izni) hemen anlaşılsın
      return page(500, "⚠️", "Bir hata oluştu", `Lütfen biraz sonra tekrar deneyin. (${errorSummary(err)})`);
    }
  },
};

async function subscription(sheets, p, env) {
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
        // Kişilerdeki bir adresten gelen e-posta Gmail'de spam'e ve çoğunlukla Promosyonlar'a düşmez
        const contact = env.EMAIL_SENDER ? ` Bültenin spam klasörüne düşmemesi için ${env.EMAIL_SENDER} `
          + "adresini kişilerinize ekleyin." : "";
        return page(200, "✓", "Aboneliğiniz Onaylandı!",
                    `Her Pazartesi sabahı güncel AI gelişmelerini gelen kutunuzda bulacaksınız.${contact}`, "#16a34a");
      }
      await sheets.put(`C${i + 1}`, [["IPTAL"]]);
      return page(200, "👋", "Abonelikten Ayrıldınız",
                  "E-posta adresiniz listeden çıkarıldı. Artık bülten almayacaksınız.", "#dc2626");
    }
  }
  return page(404, "🤔", "Kayıt bulunamadı", "Eşleşen kayıt bulunamadı veya bağlantı geçersiz.");
}

/** Geçerli görünen, başlık/SMTP komutu enjeksiyonuna izin vermeyen e-posta adresi; aksi halde null. */
export function cleanEmail(value) {
  const email = String(value || "").trim().toLowerCase();
  const part = "[^\\s@<>()\\[\\],;:\"\\\\]+";
  return email.length <= 254 && new RegExp(`^${part}@${part}\\.${part}$`).test(email) ? email : null;
}

const utcStamp = (d = new Date()) => d.toISOString().slice(0, 19).replace("T", " ");
const parseStamp = (s) => /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(s) ? Date.parse(`${s.replace(" ", "T")}Z`) : NaN;

async function signup(sheets, env, request, url) {
  const form = await request.formData().catch(() => new FormData());
  // Gizli "website" alanını yalnızca botlar doldurur; onlara başarı sayfası gösterilir, hiçbir şey yazılmaz
  if (form.get("website")) return checkInbox();
  const email = cleanEmail(form.get("email"));
  if (!email) return signupPage(env, "Lütfen geçerli bir e-posta adresi yazın.", form.get("email"), 400);

  // İlk sayfa (Form yanıtları): A zaman, B e-posta, C durum, D token. Her adresin en yeni satırı geçerlidir.
  const rows = await sheets.get("A:D");
  const now = Date.now();
  let latest = null, recent = 0;
  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][1] || "").trim().toLowerCase() === email) latest = rows[i];
    if (now - parseStamp(String(rows[i][0] || "")) < 24 * 3600 * 1000) recent++;
  }
  const status = latest ? String(latest[2] || "").trim().toUpperCase() : "";
  if (status === "AKTIF") {
    return page(200, "✓", "Zaten abonesiniz", "Bu adres listede. Bülten her Pazartesi sabahı gelir; "
                + "göremiyorsanız spam ve Promosyonlar klasörüne bakın.", "#16a34a");
  }
  if (status === "BEKLIYOR" && now - parseStamp(String(latest[0] || "")) < SIGNUP_COOLDOWN_MS) return checkInbox();
  if (recent >= SIGNUPS_PER_DAY) {
    return page(429, "⏳", "Çok fazla istek", "Bugün çok sayıda kayıt geldi. Lütfen yarın tekrar deneyin.");
  }

  const token = crypto.randomUUID();
  const link = `${url.origin}/?action=confirm&email=${encodeURIComponent(email)}&token=${encodeURIComponent(token)}`;
  // Önce e-posta: gönderilemezse tabloya satır eklenmez ve okur hemen tekrar deneyebilir
  await sendMail(env, { to: email, ...confirmEmail(link) });
  await sheets.append("A:D", [[utcStamp(), email, "BEKLIYOR", token]]);
  return checkInbox();
}

function checkInbox() {
  return page(200, "📬", "Neredeyse tamam!", "Size bir onay e-postası gönderdik. İçindeki "
              + "\"Aboneliği Onayla\" düğmesine tıkladığınızda kaydınız tamamlanır. E-posta birkaç dakika "
              + "içinde gelmezse spam klasörüne bakın.");
}

/** Onay e-postasının konusu, düz metni ve HTML'i. */
export function confirmEmail(link) {
  const href = esc(link);
  return {
    subject: "Aboneliğinizi onaylayın: AI & Teknoloji Radarı",
    text: "Merhaba,\n\nAI & Teknoloji Radarı'na abone olmak için bu bağlantıyı açın:\n"
      + `${link}\n\nBu isteği siz yapmadıysanız bu e-postayı yok sayabilirsiniz; onaylamadığınız sürece `
      + "size bülten gönderilmez.\n\nBültenin spam klasörüne düşmemesi için bu e-postanın geldiği adresi "
      + "kişilerinize ekleyin.\n",
    html: `<!DOCTYPE html><html lang="tr"><body style="margin:0;padding:32px 16px;background:#eceff4;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#10141c">
<div style="max-width:480px;margin:0 auto;background:#fff;border:1px solid #dfe3ea;padding:32px 28px">
<div style="font:700 12px sans-serif;letter-spacing:2px;margin-bottom:20px">AI &amp; TEKNOLOJİ RADARI</div>
<h1 style="font:700 24px Georgia,serif;margin:0 0 12px">Aboneliğinizi onaylayın</h1>
<p style="color:#454d5c;line-height:1.6;margin:0 0 24px">Haftalık yapay zekâ bültenine kaydolduğunuz için
teşekkürler. Kaydı tamamlamak için aşağıdaki düğmeye tıklayın.</p>
<p style="margin:0 0 24px"><a href="${href}" style="display:inline-block;background:#2563eb;color:#fff;
font-weight:600;text-decoration:none;padding:12px 22px">Aboneliği Onayla</a></p>
<p style="color:#6b7280;font-size:13px;line-height:1.5;margin:0">Düğme çalışmazsa bu adresi tarayıcınıza
yapıştırın:<br><a href="${href}" style="color:#2563eb;word-break:break-all">${href}</a></p>
<p style="color:#6b7280;font-size:13px;line-height:1.5;margin:16px 0 0">Bu isteği siz yapmadıysanız bu
e-postayı yok sayabilirsiniz; onaylamadığınız sürece size bülten gönderilmez.</p>
<p style="color:#6b7280;font-size:13px;line-height:1.5;margin:16px 0 0">İpucu: Bültenin spam klasörüne
düşmemesi için bu e-postanın geldiği adresi kişilerinize ekleyin.</p>
</div></body></html>`,
  };
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

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

const STYLE = `body{margin:0;padding:48px 16px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
sans-serif;background:#eceff4;color:#10141c;text-align:center}.card{max-width:440px;margin:0 auto;background:#fff;
border:1px solid #dfe3ea;padding:32px 24px}.big{font-size:44px}h1{font:700 24px Georgia,serif;margin:12px 0 8px}
p{color:#454d5c;line-height:1.5;margin:0}.brand{font:700 12px sans-serif;letter-spacing:2px;margin-bottom:24px}`;

function html(status, title, body, extraStyle = "", head = "") {
  return new Response(`<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>${title}</title>${head}
<style>${STYLE}${extraStyle}</style></head><body><div class="brand">AI &amp; TEKNOLOJİ RADARI</div>
${body}</body></html>`, { status, headers: { "content-type": "text/html; charset=utf-8",
                                             "cache-control": "no-store" } });
}

/** Aynı adrese kendini POST eden sayfa; JavaScript kapalıysa düğmeye basılır. */
function selfPost() {
  return html(200, "AI &amp; Teknoloji Radarı", `<div class="card"><form method="post" id="f">
<p>Kaydediliyor…</p><noscript><p><button type="submit">Devam et</button></p></noscript></form></div>
<script>document.getElementById("f").submit()</script>`, "", '<meta name="robots" content="noindex">');
}

function page(status, icon, title, text, color = "#10141c") {
  return html(status, "AI &amp; Teknoloji Radarı", `<div class="card"><div class="big">${esc(icon)}</div>
<h1 style="color:${color}">${esc(title)}</h1><p>${esc(text)}</p></div>`);
}

const SIGNUP_STYLE = `.card{max-width:480px;text-align:left;padding:36px 28px}h1{font-size:28px;line-height:1.25;
margin:0 0 12px}ul{color:#454d5c;line-height:1.6;padding-left:20px;margin:16px 0 24px}
form{display:flex;flex-wrap:wrap;gap:8px}input[type=email]{flex:1 1 220px;min-width:0;font:inherit;font-size:16px;
padding:12px;border:1px solid #c5cbd6}button{flex:0 0 auto;font:inherit;font-weight:600;font-size:16px;
padding:12px 20px;border:0;background:#2563eb;color:#fff;cursor:pointer}button:hover{background:#1d4ed8}
.err{color:#dc2626;font-size:14px;margin:0 0 8px}.small{font-size:13px;color:#6b7280;margin-top:16px}
.hp{position:absolute;left:-9999px}a{color:#2563eb}.more{margin-top:20px;font-size:14px}`;

const SIGNUP_DESC = "Haftanın yapay zekâ ve teknoloji gelişmeleri, her Pazartesi sabahı Türkçe özetle gelen kutunuzda.";

/** Bültenin kendi abonelik sayfası (Google hesabı gerektirmez). */
function signupPage(env, error = "", value = "", status = 200) {
  const archive = env.ARCHIVE_URL
    ? `<p class="more"><a href="${esc(env.ARCHIVE_URL)}">Geçmiş sayılara göz atın →</a></p>` : "";
  const head = `<meta name="description" content="${SIGNUP_DESC}">
<meta property="og:title" content="AI &amp; Teknoloji Radarı"><meta property="og:description" content="${SIGNUP_DESC}">`;
  return html(status, "AI &amp; Teknoloji Radarı: Ücretsiz Abone Olun", `<div class="card">
<h1>Haftanın yapay zekâ gelişmeleri, her Pazartesi gelen kutunuzda</h1>
<p>AI &amp; Teknoloji Radarı, haftanın öne çıkan haberlerini kısa ve Türkçe bir özetle size getirir. Ücretsizdir.</p>
<ul><li>Yeni modeller ve şirket duyuruları</li><li>Öne çıkan araştırma makaleleri</li>
<li>Gündemdeki açık kaynak projeler</li><li>Türkiye'den yapay zekâ haberleri</li></ul>
${error ? `<p class="err" role="alert">${esc(error)}</p>` : ""}
<form method="post" action="/abone"><label class="hp">Web sitesi <input name="website" tabindex="-1"
autocomplete="off"></label><input type="email" name="email" required maxlength="254" autocomplete="email"
placeholder="ornek@eposta.com" aria-label="E-posta adresiniz" value="${esc(value || "")}">
<button type="submit">Abone Ol</button></form>
<p class="small">Size bir onay e-postası göndereceğiz; kayıt, içindeki düğmeye tıkladığınızda tamamlanır.
Adresiniz yalnızca bülten için kullanılır ve her sayıdaki bağlantıyla tek tıkla ayrılabilirsiniz.</p>
${archive}</div>`, SIGNUP_STYLE, head);
}
