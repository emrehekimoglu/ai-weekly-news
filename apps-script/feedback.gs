/**
 * AI & Teknoloji Radarı: e-postadaki 👍/👎 oylarını kaydeder.
 *
 * Bu dosya mevcut iptal (unsubscribe) web uygulamasının Apps Script projesine eklenir;
 * depoda yalnızca referans için durur. Kurulum için README'deki "Feedback links" bölümüne bakın.
 *
 * 1. Bu dosyanın içeriğini projedeki feedback.gs dosyasına yapıştırın (eskisinin yerine).
 * 2. FEEDBACK_SPREADSHEET_ID'ye abone tablosunun kimliğini yazın: tablonun adresindeki
 *    /d/ ile /edit arasındaki kısım (GitHub'daki SPREADSHEET_ID secret'ı ile aynı).
 * 3. Mevcut doGet(e) fonksiyonunun EN BAŞINDA şu satır olmalı:
 *      if (e.parameter.action === 'vote') return handleVote(e);
 * 4. Dağıt → Dağıtımları yönet → mevcut dağıtımı düzenle → Sürüm: Yeni sürüm → Dağıt.
 *    (Yeni dağıtım oluşturmayın: WEB_APP_URL değişir.) Dağıtım ayarları:
 *    "Şu kullanıcı olarak yürüt: Ben" ve "Erişimi olanlar: Herkes".
 *
 * Oylar "Geri Bildirim" sayfasına yazılır: Zaman, Sayı, Haber, Oy, Okur.
 *  - Sayı: gönderim tarihi (data/history.json'daki "date" ile aynı). Önizleme oyları "onizleme-" ile başlar.
 *  - Haber: 0 = sayının tamamı, 1.. = haberin bültendeki sırası (history.json'daki entries sırası;
 *    "Türkiye'den" haberleri ana haberlerden sonra numaralanır).
 *  - Okur: e-posta değil; token ve sayıdan türetilmiş, geri çevrilemeyen kısa bir kimlik.
 *    Aynı okur aynı habere tekrar oy verirse yeni satır eklenmez, eski oyu güncellenir.
 *
 * Oy, bağlantı açılınca sunucuda hemen kaydedilir (tarayıcı tarafı google.script.run çağrısı yok;
 * o çağrı birden fazla Google hesabıyla giriş yapılmış tarayıcılarda ve gizli pencerede başarısız oluyordu).
 * Bir hata olursa sayfa hatanın kendisini gösterir, böylece sorun kurulumda mı kodda mı hemen görülür.
 */

var FEEDBACK_SHEET_NAME = 'Geri Bildirim';
// Abone tablosunun kimliği (https://docs.google.com/spreadsheets/d/<KİMLİK>/edit).
var FEEDBACK_SPREADSHEET_ID = '';

function handleVote(e) {
  var vote = cleanVote_(e.parameter || {});
  if (!vote) {
    return votePage_('🤔', 'Bağlantı geçersiz', 'Bu oy bağlantısı tanınmadı.');
  }
  try {
    recordVote_(vote);
  } catch (err) {
    console.error('Oy kaydedilemedi: ' + err);
    return votePage_('⚠️', 'Oy kaydedilemedi', 'Hata: ' + err.message);
  }
  return votePage_(vote.v === 'up' ? '👍' : '👎', 'Teşekkürler!',
                   'Oyunuz kaydedildi. Fikrinizi değiştirirseniz diğer bağlantıya tıklamanız yeterli.');
}

function recordVote_(vote) {
  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    var sheet = feedbackSheet_();
    var row = [new Date(), vote.issue, vote.story, vote.v, vote.voter || 'anonim'];
    if (vote.voter) {
      var values = sheet.getDataRange().getValues();
      for (var i = values.length - 1; i >= 1; i--) {
        if (String(values[i][1]) === vote.issue && Number(values[i][2]) === vote.story &&
            String(values[i][4]) === vote.voter) {
          sheet.getRange(i + 1, 1, 1, row.length).setValues([row]);
          return;
        }
      }
    }
    sheet.appendRow(row);
  } finally {
    lock.releaseLock();
  }
}

/** Sadece beklenen biçimdeki değerleri kabul eder; aksi halde null. */
function cleanVote_(p) {
  var issue = String(p.issue || '');
  var story = String(p.story || '');
  var v = String(p.v || '');
  var voter = String(p.voter || '');
  if (!/^(onizleme-)?\d{4}-\d{2}-\d{2}$/.test(issue)) return null;
  if (!/^\d{1,2}$/.test(story)) return null;
  if (v !== 'up' && v !== 'down') return null;
  if (!/^[0-9a-f]{0,16}$/.test(voter)) return null;
  return { issue: issue, story: Number(story), v: v, voter: voter };
}

function feedbackSheet_() {
  var book = FEEDBACK_SPREADSHEET_ID ? SpreadsheetApp.openById(FEEDBACK_SPREADSHEET_ID)
                                     : SpreadsheetApp.getActiveSpreadsheet();
  if (!book) {
    throw new Error('Tablo bulunamadı: feedback.gs içindeki FEEDBACK_SPREADSHEET_ID boş.');
  }
  var sheet = book.getSheetByName(FEEDBACK_SHEET_NAME);
  if (!sheet) {
    sheet = book.insertSheet(FEEDBACK_SHEET_NAME);
    sheet.appendRow(['Zaman', 'Sayı', 'Haber', 'Oy', 'Okur']);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function votePage_(icon, title, text) {
  var esc = function (s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  };
  var html =
    '<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">' +
    '<style>body{margin:0;padding:48px 20px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;' +
    'background:#eceff4;color:#10141c;text-align:center}.card{max-width:420px;margin:0 auto;background:#fff;' +
    'border:1px solid #dfe3ea;padding:32px 24px}.big{font-size:44px}h1{font:700 24px Georgia,serif;margin:12px 0 8px}' +
    'p{color:#454d5c;line-height:1.5;margin:0}</style></head><body><div class="card">' +
    '<div class="big">' + esc(icon) + '</div><h1>' + esc(title) + '</h1><p>' + esc(text) + '</p></div></body></html>';
  return HtmlService.createHtmlOutput(html)
    .setTitle('AI & Teknoloji Radarı')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}
