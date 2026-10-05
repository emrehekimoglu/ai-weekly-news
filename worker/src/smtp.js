/**
 * Gmail SMTP üzerinden tek bir e-posta gönderir (bültenin kullandığı EMAIL_SENDER / EMAIL_PASSWORD ile).
 *
 * Workers'ta SMTP kütüphanesi yok; cloudflare:sockets ile smtp.gmail.com:465'e TLS bağlantısı açılır ve
 * EHLO → AUTH PLAIN → MAIL FROM → RCPT TO → DATA adımları sırayla yürütülür.
 */

const enc = new TextEncoder();

// Testler gerçek soket yerine sahtesini koyar; Node'da cloudflare:sockets yoktur, bu yüzden geç yüklenir
export const smtp = {
  connect: async (address, options) => (await import("cloudflare:sockets")).connect(address, options),
};

/** UTF-8 metni base64'e çevirir (btoa yalnızca Latin-1 kabul eder). */
export function b64utf8(text) {
  const bytes = enc.encode(text);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

const wrap = (s) => s.replace(/.{1,76}/g, "$&\r\n");
const word = (s) => `=?UTF-8?B?${b64utf8(s)}?=`;

/** Düz metin + HTML içeren MIME iletisi (base64 gövdeler; satırlar asla "." ile başlamaz). */
export function buildMessage({ from, fromName, to, subject, text, html }) {
  const boundary = `radar-${crypto.randomUUID()}`;
  const part = (type, body) => `--${boundary}\r\nContent-Type: ${type}; charset=utf-8\r\n`
    + `Content-Transfer-Encoding: base64\r\n\r\n${wrap(b64utf8(body))}`;
  return [
    `From: ${word(fromName)} <${from}>`,
    `To: <${to}>`,
    `Subject: ${word(subject)}`,
    `Date: ${new Date().toUTCString().replace("GMT", "+0000")}`,
    `Message-ID: <${crypto.randomUUID()}@${from.split("@")[1]}>`,
    "MIME-Version: 1.0",
    `Content-Type: multipart/alternative; boundary="${boundary}"`,
    "",
    part("text/plain", text) + part("text/html", html) + `--${boundary}--`,
  ].join("\r\n");
}

export async function sendMail(env, { to, subject, text, html }) {
  const user = env.EMAIL_SENDER, pass = env.EMAIL_PASSWORD;
  if (!user || !pass) throw new Error("E-posta ayarı eksik: EMAIL_SENDER / EMAIL_PASSWORD");
  const message = buildMessage({ from: user, fromName: "AI & Teknoloji Radarı", to, subject, text, html });

  const socket = await smtp.connect({ hostname: "smtp.gmail.com", port: 465 }, { secureTransport: "on" });
  const writer = socket.writable.getWriter();
  const reader = socket.readable.getReader();
  const dec = new TextDecoder();
  let buf = "";

  // Sunucu yanıtını okur; çok satırlı yanıtlarda ("250-…") son satıra ("250 …") kadar bekler
  async function expect(code) {
    const lines = [];
    for (;;) {
      const end = buf.indexOf("\r\n");
      if (end < 0) {
        const { value, done } = await reader.read();
        if (done) throw new Error(`SMTP bağlantısı kapandı (${code} bekleniyordu)`);
        buf += dec.decode(value, { stream: true });
        continue;
      }
      const line = buf.slice(0, end);
      buf = buf.slice(end + 2);
      lines.push(line);
      if (/^\d{3}(?!-)/.test(line)) break;
    }
    const last = lines[lines.length - 1];
    if (!last.startsWith(String(code))) throw new Error(`SMTP ${last.slice(0, 3)}: ${last.slice(4, 160)}`);
  }
  const send = (line) => writer.write(enc.encode(`${line}\r\n`));

  try {
    await expect(220);
    await send("EHLO ai-radar.workers.dev");
    await expect(250);
    await send(`AUTH PLAIN ${b64utf8(`\0${user}\0${pass}`)}`);
    await expect(235);
    await send(`MAIL FROM:<${user}>`);
    await expect(250);
    await send(`RCPT TO:<${to}>`);
    await expect(250);
    await send("DATA");
    await expect(354);
    await writer.write(enc.encode(`${message.replace(/^\./gm, "..")}\r\n.\r\n`));
    await expect(250);
    await send("QUIT");
  } finally {
    await socket.close().catch(() => {});
  }
}
