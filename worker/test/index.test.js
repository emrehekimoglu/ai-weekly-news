// Worker'ı sahte Google uç noktalarıyla dener (ağ yok): node --test
import { test } from "node:test";
import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import worker, { cleanEmail, cleanVote } from "../src/index.js";
import { smtp } from "../src/smtp.js";

const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const env = {
  GCP_SA_KEY: JSON.stringify({ client_email: "sa@example.iam.gserviceaccount.com",
                               private_key: privateKey.export({ type: "pkcs8", format: "pem" }) }),
  SPREADSHEET_ID: "SHEET",
  EMAIL_SENDER: "bulten@gmail.com",
  EMAIL_PASSWORD: "app pass",
  ARCHIVE_URL: "https://arsiv.example/",
};

const LATEST_URL = "https://raw.example/data/latest-issue.json";

/** Bellekte duran sahte tablo: { "": ilk sayfa satırları, "Geri Bildirim": ... } */
function fakeGoogle(tabs, latest = null) {
  const calls = [];
  // Workers'taki gibi: fetch başka bir nesneye bağlı çağrılırsa hata verir
  globalThis.fetch = async function (url, opts = {}) {
    if (this !== undefined && this !== globalThis) throw new TypeError("Illegal invocation");
    calls.push({ url, method: opts.method || "GET", body: opts.body });
    // GitHub'daki data/latest-issue.json (hoş geldin e-postası)
    if (url === LATEST_URL) return latest ? Response.json(latest) : new Response("404: Not Found", { status: 404 });
    if (url.startsWith("https://oauth2.googleapis.com")) return Response.json({ access_token: "tok" });
    const path = decodeURIComponent(url.split("/spreadsheets/SHEET")[1].split("?")[0]);
    if (path === ":batchUpdate") {
      tabs[JSON.parse(opts.body).requests[0].addSheet.properties.title] = [];
      return Response.json({});
    }
    const m = path.match(/^\/values\/(?:'(.+)'!)?([A-Z])(\d*)(?::([A-Z])(\d*))?(:append)?$/);
    const tab = m[1] || "";
    if (!(tab in tabs)) return new Response("Unable to parse range", { status: 400 });
    const rows = tabs[tab];
    if (m[6]) { rows.push(...JSON.parse(opts.body).values); return Response.json({}); }
    if (opts.method === "PUT") {
      const r = Number(m[3]) - 1, c = m[2].charCodeAt(0) - 65;
      JSON.parse(opts.body).values[0].forEach((v, k) => { (rows[r] ||= [])[c + k] = v; });
      return Response.json({});
    }
    return Response.json({ values: rows });
  };
  return calls;
}

const get = (qs) => worker.fetch(new Request(`https://ai-radar.example.workers.dev/?${qs}`), env);
// Oy ve iptal, GET'te kendini gönderen sayfa döner; tarayıcının o sayfadan attığı POST'u taklit eder
const act = (qs) => worker.fetch(new Request(`https://ai-radar.example.workers.dev/?${qs}`, { method: "POST" }), env);

test("confirm and unsubscribe update column C of the matching row", async () => {
  const tabs = { "": [["Zaman", "E-posta", "Durum", "Token"], ["t", "a@x.com", "BEKLIYOR", "tok-a"],
                     ["t", "b@x.com", "AKTIF", "tok-b"]] };
  fakeGoogle(tabs);
  let res = await get("action=confirm&email=A%40x.com&token=tok-a");
  assert.equal(res.status, 200);
  const body = await res.text();
  assert.match(body, /Aboneliğiniz Onaylandı/);
  assert.match(body, /bulten@gmail\.com adresini kişilerinize ekleyin/);
  assert.equal(tabs[""][1][2], "AKTIF");

  res = await act("action=unsubscribe&email=b%40x.com&token=tok-b");
  assert.match(await res.text(), /Abonelikten Ayrıldınız/);
  assert.equal(tabs[""][2][2], "IPTAL");
});

test("one-click unsubscribe (RFC 8058 POST from Gmail's button) works on the same link", async () => {
  const tabs = { "": [["Zaman", "E-posta", "Durum", "Token"], ["t", "b@x.com", "AKTIF", "tok-b"]] };
  fakeGoogle(tabs);
  const res = await worker.fetch(new Request("https://ai-radar.example.workers.dev/?action=unsubscribe&email=b%40x.com&token=tok-b",
    { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" },
      body: "List-Unsubscribe=One-Click" }), env);
  assert.equal(res.status, 200);
  assert.equal(tabs[""][1][2], "IPTAL");
});

test("link scanners (GET/HEAD without JavaScript) can't vote or unsubscribe", async () => {
  const tabs = { "": [["h"], ["t", "a@x.com", "AKTIF", "tok-a"]] };
  const calls = fakeGoogle(tabs);
  for (const qs of ["action=vote&issue=2026-10-12&story=1&v=up&voter=abc", "action=unsubscribe&email=a%40x.com&token=tok-a"]) {
    const res = await get(qs);
    assert.equal(res.status, 200);
    assert.match(await res.text(), /<form method="post" id="f">[\s\S]*\.submit\(\)/);
    const head = await worker.fetch(new Request(`https://ai-radar.example.workers.dev/?${qs}`, { method: "HEAD" }), env);
    assert.equal(head.status, 200);
  }
  assert.equal(calls.length, 0);
  assert.equal(tabs[""][1][2], "AKTIF");
  assert.equal((await get("action=unsubscribe&email=a%40x.com")).status, 400);
});

test("wrong token changes nothing", async () => {
  const tabs = { "": [["h"], ["t", "a@x.com", "AKTIF", "tok-a"]] };
  fakeGoogle(tabs);
  const res = await act("action=unsubscribe&email=a%40x.com&token=yanlis");
  assert.equal(res.status, 404);
  assert.equal(tabs[""][1][2], "AKTIF");
});

test("votes create the sheet, then replace a reader's earlier vote", async () => {
  const tabs = { "": [] };
  fakeGoogle(tabs);
  await act("action=vote&issue=2026-10-12&story=3&v=up&voter=abc123");
  assert.deepEqual(tabs["Geri Bildirim"][0], ["Zaman", "Sayı", "Haber", "Oy", "Okur"]);
  assert.deepEqual(tabs["Geri Bildirim"].slice(1).map((r) => r.slice(1)), [["2026-10-12", 3, "up", "abc123"]]);

  const res = await act("action=vote&issue=2026-10-12&story=3&v=down&voter=abc123");
  assert.match(await res.text(), /Teşekkürler/);
  await act("action=vote&issue=2026-10-12&story=0&v=up");
  assert.deepEqual(tabs["Geri Bildirim"].slice(1).map((r) => r.slice(1)),
                   [["2026-10-12", 3, "down", "abc123"], ["2026-10-12", 0, "up", "anonim"]]);
});

test("invalid requests are rejected without touching the sheet", async () => {
  const calls = fakeGoogle({ "": [] });
  for (const qs of ["action=nope", "action=vote&issue=x&story=1&v=up", "action=vote&issue=2026-10-12&story=1&v=meh",
                    "action=confirm&email=a%40x.com"]) {
    assert.equal((await get(qs)).status, 400);
  }
  assert.equal(calls.length, 0);
  assert.deepEqual(cleanVote({ issue: "onizleme-2026-10-12", story: "12", v: "up", voter: "" }),
                   { issue: "onizleme-2026-10-12", story: 12, v: "up", voter: "" });
});

test("errors show Google's short message on the page, not the request", async () => {
  globalThis.fetch = async (url) => url.startsWith("https://oauth2")
    ? Response.json({ access_token: "tok" })
    : new Response(JSON.stringify({ error: { code: 403, message: "The caller does not have permission" } }),
                   { status: 403 });
  const res = await act("action=unsubscribe&email=a%40x.com&token=t");
  assert.equal(res.status, 500);
  const html = await res.text();
  assert.match(html, /Sheets API 403: The caller does not have permission/);
  assert.doesNotMatch(html, /SHEET/);
});

/** Gmail yerine konuşan sahte SMTP sunucusu; gönderilen komutları ve iletileri kaydeder. */
function fakeSmtp({ rejectAuth = false } = {}) {
  const log = { commands: [], messages: [], connects: [] };
  smtp.connect = async (address, options) => {
    log.connects.push({ address, options });
    const enc = new TextEncoder(), dec = new TextDecoder();
    let push, inData = false, data = "";
    const readable = new ReadableStream({ start(c) { push = (s) => c.enqueue(enc.encode(s)); } });
    push("220 smtp.gmail.com ESMTP\r\n");
    const writable = new WritableStream({ write(chunk) {
      const text = dec.decode(chunk);
      if (inData) {
        data += text;
        if (data.endsWith("\r\n.\r\n")) { inData = false; log.messages.push(data); push("250 2.0.0 OK\r\n"); }
        return;
      }
      const cmd = text.trimEnd();
      log.commands.push(cmd);
      if (cmd.startsWith("EHLO")) push("250-smtp.gmail.com\r\n250-AUTH LOGIN PLAIN\r\n250 SMTPUTF8\r\n");
      else if (cmd.startsWith("AUTH")) push(rejectAuth ? "535 5.7.8 Username and Password not accepted\r\n"
                                                        : "235 2.7.0 Accepted\r\n");
      else if (cmd === "DATA") { inData = true; push("354 Go ahead\r\n"); }
      else if (cmd !== "QUIT") push("250 OK\r\n");
    } });
    return { readable, writable, close: async () => {} };
  };
  return log;
}

const post = (body, path = "/abone") => worker.fetch(new Request(`https://ai-radar.example.workers.dev${path}`, {
  method: "POST", body: new URLSearchParams(body) }), env);

const decodeParts = (msg) => [...msg.matchAll(/base64\r\n\r\n([A-Za-z0-9+/=\r\n]+?)\r\n--/g)]
  .map((m) => Buffer.from(m[1].replace(/\r\n/g, ""), "base64").toString("utf8"));

test("signup page is served on /abone and on the bare address", async () => {
  const calls = fakeGoogle({ "": [] });
  for (const path of ["/abone", "/"]) {
    const res = await worker.fetch(new Request(`https://ai-radar.example.workers.dev${path}`), env);
    assert.equal(res.status, 200);
    const html = await res.text();
    assert.match(html, /<form method="post" action="\/abone">/);
    assert.match(html, /href="https:\/\/arsiv.example\/"/);
  }
  assert.equal(calls.length, 0);
});

test("signup adds a BEKLIYOR row and emails a working confirm link", async () => {
  const tabs = { "": [["Zaman", "E-posta", "Durum", "Token"]] };
  fakeGoogle(tabs);
  const mail = fakeSmtp();
  const res = await post({ email: "  Yeni@Ornek.com ", website: "" });
  assert.equal(res.status, 200);
  assert.match(await res.text(), /Neredeyse tamam/);

  const [, email, status, token] = tabs[""][1];
  assert.deepEqual([email, status], ["yeni@ornek.com", "BEKLIYOR"]);
  assert.match(tabs[""][1][0], /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);

  assert.deepEqual(mail.connects[0], { address: { hostname: "smtp.gmail.com", port: 465 },
                                       options: { secureTransport: "on" } });
  assert.deepEqual(mail.commands, ["EHLO ai-radar.workers.dev",
    `AUTH PLAIN ${Buffer.from("\0bulten@gmail.com\0app pass").toString("base64")}`,
    "MAIL FROM:<bulten@gmail.com>", "RCPT TO:<yeni@ornek.com>", "DATA", "QUIT"]);
  const msg = mail.messages[0];
  assert.match(msg, /^From: =\?UTF-8\?B\?.+\?= <bulten@gmail.com>\r\nTo: <yeni@ornek.com>\r\n/);
  const [text, html] = decodeParts(msg);
  const link = `https://ai-radar.example.workers.dev/?action=confirm&email=yeni%40ornek.com&token=${token}`;
  assert.ok(text.includes(link));
  assert.ok(html.includes(link.replace(/&/g, "&amp;")));

  // Bağlantı açılınca aynı satır AKTIF olur
  const confirmed = await worker.fetch(new Request(link), env);
  assert.match(await confirmed.text(), /Aboneliğiniz Onaylandı/);
  assert.equal(tabs[""][1][2], "AKTIF");
});

test("active subscribers, repeats within 10 minutes and bots get no new email", async () => {
  const now = new Date().toISOString().slice(0, 19).replace("T", " ");
  const tabs = { "": [["h"], ["05.10.2026 10:00:00", "a@x.com", "AKTIF", "t1"], [now, "b@x.com", "BEKLIYOR", "t2"]] };
  fakeGoogle(tabs);
  const mail = fakeSmtp();
  assert.match(await (await post({ email: "A@x.com" })).text(), /Zaten abonesiniz/);
  assert.match(await (await post({ email: "b@x.com" })).text(), /Neredeyse tamam/);
  assert.match(await (await post({ email: "c@x.com", website: "http://spam" })).text(), /Neredeyse tamam/);
  assert.equal(tabs[""].length, 3);
  assert.equal(mail.messages.length, 0);

  // Ayrılmış biri yeniden abone olabilir: yeni satır eklenir
  tabs[""][1][2] = "IPTAL";
  await post({ email: "a@x.com" });
  assert.equal(tabs[""].length, 4);
  assert.equal(mail.messages.length, 1);
});

test("signup rejects bad addresses and stops after the daily limit", async () => {
  const now = new Date().toISOString().slice(0, 19).replace("T", " ");
  const tabs = { "": [["h"], ...Array.from({ length: 50 }, (_, i) => [now, `u${i}@x.com`, "BEKLIYOR", "t"])] };
  const calls = fakeGoogle(tabs);
  const mail = fakeSmtp();
  for (const bad of ["", "abc", "a@b", "a b@x.com", "a@x.com\r\nBcc: z@x.com", "<a@x.com>"]) {
    const res = await post({ email: bad });
    assert.equal(res.status, 400);
    assert.match(await res.text(), /geçerli bir e-posta/);
  }
  assert.equal(calls.length, 0);
  assert.equal((await post({ email: "new@x.com" })).status, 429);
  assert.equal(tabs[""].length, 51);
  assert.equal(mail.messages.length, 0);
  assert.equal(cleanEmail(" Ali.Veli+radar@Ornek.com.tr "), "ali.veli+radar@ornek.com.tr");
});

test("a Gmail login failure shows the SMTP error, never the password", async () => {
  const tabs = { "": [["h"]] };
  fakeGoogle(tabs);
  fakeSmtp({ rejectAuth: true });
  const res = await post({ email: "a@x.com" });
  assert.equal(res.status, 500);
  const html = await res.text();
  assert.match(html, /SMTP 535: 5.7.8 Username and Password not accepted/);
  assert.doesNotMatch(html, /app pass/);
  assert.equal(tabs[""].length, 1);  // satır eklenmedi, okur hemen tekrar deneyebilir
});

// newsletter/welcome.py'nin kaydettiği biçim (yer tutucularla)
const LATEST = {
  issue: "2026-10-12",
  subject: "Açık kaynak arayı kapattı mı? • Radar, 12 Ekim 2026",
  html: '<p>Hoş geldiniz!</p><a href="__RADAR_BASE__?action=vote&amp;issue=2026-10-12&amp;story=1&amp;v=up&amp;voter=__RADAR_VOTER__">👍</a>'
    + '<a href="__RADAR_UNSUBSCRIBE__">iptal</a>',
  text: "Hoş geldiniz!\n👍 __RADAR_BASE__?action=vote&issue=2026-10-12&story=0&v=up&voter=__RADAR_VOTER__\n"
    + "Ayrılmak için: __RADAR_UNSUBSCRIBE__\n",
};

/** Workers'taki ctx: waitUntil'e verilen işleri test sonunda bekler. */
function fakeCtx() {
  const tasks = [];
  return { waitUntil: (p) => tasks.push(p), done: () => Promise.all(tasks) };
}

const confirm = async (qs, ctx) => worker.fetch(new Request(`https://ai-radar.example.workers.dev/?${qs}`),
                                                { ...env, LATEST_ISSUE_URL: LATEST_URL }, ctx);

test("confirming sends the latest issue with the reader's own unsubscribe and vote links", async () => {
  const tabs = { "": [["h"], ["t", "a@x.com", "BEKLIYOR", "tok-a"]] };
  fakeGoogle(tabs, LATEST);
  const mail = fakeSmtp();
  const ctx = fakeCtx();
  const res = await confirm("action=confirm&email=a%40x.com&token=tok-a", ctx);
  assert.match(await res.text(), /son sayıyı da şimdi e-posta adresinize gönderiyoruz/);
  await ctx.done();
  assert.equal(tabs[""][1][2], "AKTIF");

  assert.equal(mail.messages.length, 1);
  assert.ok(mail.commands.includes("RCPT TO:<a@x.com>"));
  const msg = mail.messages[0];
  const unsub = "https://ai-radar.example.workers.dev/?action=unsubscribe&email=a%40x.com&token=tok-a";
  assert.ok(msg.includes(`\r\nList-Unsubscribe: <${unsub}>\r\nList-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n`));
  const subject = msg.match(/^Subject: =\?UTF-8\?B\?(.+)\?=$/m)[1];
  assert.equal(Buffer.from(subject, "base64").toString("utf8"), `Hoş geldiniz! ${LATEST.subject}`);

  const [text, html] = decodeParts(msg);
  assert.doesNotMatch(text + html, /__RADAR_/);
  // newsletter/mailer.py ile aynı okur kimliği: sha256("2026-10-12:tok-a")[:12]
  assert.ok(text.includes("https://ai-radar.example.workers.dev/?action=vote&issue=2026-10-12&story=0&v=up&voter=73e77b03bfa5"));
  assert.ok(text.includes(`Ayrılmak için: ${unsub}\n`));
  assert.ok(html.includes('href="https://ai-radar.example.workers.dev/?action=vote&amp;issue=2026-10-12&amp;story=1&amp;v=up&amp;voter=73e77b03bfa5"'));
  assert.ok(html.includes(`href="${unsub.replace(/&/g, "&amp;")}"`));

  // Oy bağlantısı Worker'da geçerli
  assert.ok(cleanVote({ issue: "2026-10-12", story: "1", v: "up", voter: "73e77b03bfa5" }));
});

test("no welcome email for an already active reader or when there is no saved issue yet", async () => {
  let tabs = { "": [["h"], ["t", "a@x.com", "AKTIF", "tok-a"]] };
  fakeGoogle(tabs, LATEST);
  const mail = fakeSmtp();
  let ctx = fakeCtx();
  let res = await confirm("action=confirm&email=a%40x.com&token=tok-a", ctx);
  assert.doesNotMatch(await res.text(), /son sayıyı/);
  await ctx.done();

  tabs = { "": [["h"], ["t", "b@x.com", "BEKLIYOR", "tok-b"]] };
  fakeGoogle(tabs);  // latest-issue.json henüz yok (404)
  ctx = fakeCtx();
  res = await confirm("action=confirm&email=b%40x.com&token=tok-b", ctx);
  const body = await res.text();
  assert.match(body, /Aboneliğiniz Onaylandı/);
  assert.doesNotMatch(body, /son sayıyı/);
  await ctx.done();
  assert.equal(tabs[""][1][2], "AKTIF");
  assert.equal(mail.messages.length, 0);
});

test("a failed welcome email still confirms the subscription", async () => {
  const tabs = { "": [["h"], ["t", "a@x.com", "BEKLIYOR", "tok-a"]] };
  fakeGoogle(tabs, LATEST);
  fakeSmtp({ rejectAuth: true });
  const ctx = fakeCtx();
  const res = await confirm("action=confirm&email=a%40x.com&token=tok-a", ctx);
  assert.equal(res.status, 200);
  await ctx.done();  // hata yutulur, sadece loglanır
  assert.equal(tabs[""][1][2], "AKTIF");
});
