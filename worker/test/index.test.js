// Worker'ı sahte Google uç noktalarıyla dener (ağ yok): node --test
import { test } from "node:test";
import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import worker, { cleanVote } from "../src/index.js";

const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const env = {
  GCP_SA_KEY: JSON.stringify({ client_email: "sa@example.iam.gserviceaccount.com",
                               private_key: privateKey.export({ type: "pkcs8", format: "pem" }) }),
  SPREADSHEET_ID: "SHEET",
};

/** Bellekte duran sahte tablo: { "": ilk sayfa satırları, "Geri Bildirim": ... } */
function fakeGoogle(tabs) {
  const calls = [];
  globalThis.fetch = async (url, opts = {}) => {
    calls.push({ url, method: opts.method || "GET", body: opts.body });
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

test("confirm and unsubscribe update column C of the matching row", async () => {
  const tabs = { "": [["Zaman", "E-posta", "Durum", "Token"], ["t", "a@x.com", "BEKLIYOR", "tok-a"],
                     ["t", "b@x.com", "AKTIF", "tok-b"]] };
  fakeGoogle(tabs);
  let res = await get("action=confirm&email=A%40x.com&token=tok-a");
  assert.equal(res.status, 200);
  assert.match(await res.text(), /Aboneliğiniz Onaylandı/);
  assert.equal(tabs[""][1][2], "AKTIF");

  res = await get("action=unsubscribe&email=b%40x.com&token=tok-b");
  assert.match(await res.text(), /Abonelikten Ayrıldınız/);
  assert.equal(tabs[""][2][2], "IPTAL");
});

test("wrong token changes nothing", async () => {
  const tabs = { "": [["h"], ["t", "a@x.com", "AKTIF", "tok-a"]] };
  fakeGoogle(tabs);
  const res = await get("action=unsubscribe&email=a%40x.com&token=yanlis");
  assert.equal(res.status, 404);
  assert.equal(tabs[""][1][2], "AKTIF");
});

test("votes create the sheet, then replace a reader's earlier vote", async () => {
  const tabs = { "": [] };
  fakeGoogle(tabs);
  await get("action=vote&issue=2026-10-12&story=3&v=up&voter=abc123");
  assert.deepEqual(tabs["Geri Bildirim"][0], ["Zaman", "Sayı", "Haber", "Oy", "Okur"]);
  assert.deepEqual(tabs["Geri Bildirim"].slice(1).map((r) => r.slice(1)), [["2026-10-12", 3, "up", "abc123"]]);

  const res = await get("action=vote&issue=2026-10-12&story=3&v=down&voter=abc123");
  assert.match(await res.text(), /Teşekkürler/);
  await get("action=vote&issue=2026-10-12&story=0&v=up");
  assert.deepEqual(tabs["Geri Bildirim"].slice(1).map((r) => r.slice(1)),
                   [["2026-10-12", 3, "down", "abc123"], ["2026-10-12", 0, "up", "anonim"]]);
});

test("invalid requests are rejected without touching the sheet", async () => {
  const calls = fakeGoogle({ "": [] });
  for (const qs of ["", "action=vote&issue=x&story=1&v=up", "action=vote&issue=2026-10-12&story=1&v=meh",
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
  const res = await get("action=unsubscribe&email=a%40x.com&token=t");
  assert.equal(res.status, 500);
  const html = await res.text();
  assert.match(html, /Sheets API 403: The caller does not have permission/);
  assert.doesNotMatch(html, /SHEET/);
});
