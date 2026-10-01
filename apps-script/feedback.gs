/**
 * AI & Teknoloji Radarı: e-postadaki 👍/👎 oylarını kaydeder.
 *
 * Bu dosya mevcut iptal (unsubscribe) web uygulamasının Apps Script projesine eklenir;
 * depoda yalnızca referans için durur. Kurulum için README'deki "Feedback links" bölümüne bakın.
 *
 * 1. Bu dosyayı projede yeni bir betik dosyası olarak ekleyin (feedback.gs).
 * 2. Mevcut doGet(e) fonksiyonunun EN BAŞINA şu satırı ekleyin:
 *      if (e.parameter.action === 'vote') return handleVote(e);
 * 3. Dağıt → Dağıtımları yönet → mevcut dağıtımı düzenle → Sürüm: Yeni sürüm → Dağıt.
 *    (Yeni dağıtım oluşturmayın: WEB_APP_URL değişir.)
 *
 * Oylar "Geri Bildirim" sayfasına yazılır: Zaman, Sayı, Haber, Oy, Okur.
 *  - Sayı: gönderim tarihi (data/history.json'daki "date" ile aynı). Önizleme oyları "onizleme-" ile başlar.
 *  - Haber: 0 = sayının tamamı, 1.. = haberin bültendeki sırası (history.json'daki entries sırası).
 *  - Okur: e-posta değil; token ve sayıdan türetilmiş, geri çevrilemeyen kısa bir kimlik.
 *    Aynı okur aynı habere tekrar oy verirse yeni satır eklenmez, eski oyu güncellenir.
 *
 * Oy, sayfa açılınca tarayıcıdaki betikle kaydedilir. E-posta tarayıcılarının ve güvenlik
 * tarayıcılarının bağlantıları önceden açması (JavaScript çalıştırmadan) böylece oy sayılmaz.
 */

var FEEDBACK_SHEET_NAME = 'Geri Bildirim';
// Betik abone tablosuna bağlı değilse (bağımsız proje) tablonun kimliğini buraya yazın.
var FEEDBACK_SPREADSHEET_ID = '';

function handleVote(e) {
  var vote = cleanVote_(e.parameter || {});
  var page = HtmlService.createTemplate(FEEDBACK_PAGE_);
  page.voteJson = JSON.stringify(vote);
  return page.evaluate()
    .setTitle('AI & Teknoloji Radarı')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/** Oy sayfasındaki betik çağırır (google.script.run). */
function recordVote(params) {
  var vote = cleanVote_(params || {});
  if (!vote) throw new Error('Geçersiz oy');

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
          return true;
        }
      }
    }
    sheet.appendRow(row);
    return true;
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
  var sheet = book.getSheetByName(FEEDBACK_SHEET_NAME);
  if (!sheet) {
    sheet = book.insertSheet(FEEDBACK_SHEET_NAME);
    sheet.appendRow(['Zaman', 'Sayı', 'Haber', 'Oy', 'Okur']);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

var FEEDBACK_PAGE_ = [
  '<!DOCTYPE html><html lang="tr"><head><base target="_top"><meta charset="utf-8">',
  '<style>body{margin:0;padding:48px 20px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;',
  'background:#eceff4;color:#10141c;text-align:center}.card{max-width:420px;margin:0 auto;background:#fff;',
  'border:1px solid #dfe3ea;padding:32px 24px}.big{font-size:44px}h1{font:700 24px Georgia,serif;margin:12px 0 8px}',
  'p{color:#454d5c;line-height:1.5;margin:0}</style></head><body><div class="card">',
  '<div class="big" id="icon">⏳</div><h1 id="title">Oyunuz kaydediliyor…</h1><p id="text"></p></div>',
  '<script>',
  'var vote = <?!= voteJson ?>;',
  'function show(icon, title, text) {',
  '  document.getElementById("icon").textContent = icon;',
  '  document.getElementById("title").textContent = title;',
  '  document.getElementById("text").textContent = text;',
  '}',
  'if (!vote) {',
  '  show("🤔", "Bağlantı geçersiz", "Bu oy bağlantısı tanınmadı.");',
  '} else {',
  '  google.script.run',
  '    .withSuccessHandler(function () {',
  '      show(vote.v === "up" ? "👍" : "👎", "Teşekkürler!",',
  '           "Oyunuz kaydedildi. Fikrinizi değiştirirseniz diğer bağlantıya tıklamanız yeterli.");',
  '    })',
  '    .withFailureHandler(function () { show("⚠️", "Oy kaydedilemedi", "Lütfen biraz sonra tekrar deneyin."); })',
  '    .recordVote(vote);',
  '}',
  '</script></body></html>'
].join('\n');
