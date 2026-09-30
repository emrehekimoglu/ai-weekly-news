"""OpenCode Go üzerinden LLM ile bülten HTML'i üretimi ve doğrulaması."""

import logging
import re
import time
import uuid

from openai import OpenAI

from newsletter import config

log = logging.getLogger(__name__)

SYSTEM_PROMPT = "Sen profesyonel bir teknoloji bülteni editörüsün."

PROMPT = """
Sen dünya standartlarında kıdemli bir yapay zeka ve teknoloji baş editörüsün.
Aşağıda son bir haftada yayımlanan ham teknoloji haberleri, makaleler, model duyuruları ve viral topluluk tartışmaları (orijinal tarihleriyle birlikte) yer alıyor:

{raw_data}

GÖREVİN:
Bu verileri titizlikle filtreleyerek haftanın EN ÖNEMLİ 10 gelişmesini seç.
(Eğer bu hafta gerçekten kaçırılmaması gereken çok kritik gelişmeler olduysa en fazla 12'ye kadar esneyebilirsin; yani toplam 10 ila 12 madde seç).

İÇERİK SEÇİMİNDE ÖNCELİK SIRAN (ÇOK ÖNEMLİ):
1. YENİ MODEL LANSMANLARI: Yeni bir GPT, Claude, Gemini, Grok, Llama veya güçlü açık kaynak model duyurulduysa MUTLAKA İLK SIRALARDA YER VER.
2. VİRAL / SKANDAL / GÜVENLİK OLAYLARI: Modellerin beklenmedik/çıldıran davranışları, güvenlik filtrelerinin çökmesi (jailbreak), sansür tartışmaları veya büyük şirket krizleri varsa MUTLAKA BÜLTENE DAHİL ET.
3. ÇIĞIR AÇICI ARAŞTIRMALAR & AÇIK KAYNAK: Yeni bir mimari öneren akademik çalışmalar ve GitHub'da patlayan açık kaynak projeler.

ŞABLON VE TASARIM KURALLARI:
1. Türkçe yaz.
2. EN ÜSTE ŞIK BİR HEADER ALANI EKLE:
   - Yuvarlak yapay zekâ ikonu (harici görsel KULLANMA, birebir bu kodu kullan): `<span style="display: inline-block; width: 44px; height: 44px; line-height: 44px; border-radius: 50%; background: #2563eb; color: #ffffff; text-align: center; font-size: 24px; vertical-align: middle; margin-right: 12px;">🤖</span>`
   - Yanına kalın ve modern bir fontla "AI & TEKNOLOJİ RADARI" başlığı.
   - Altına gri ve küçük puntolarla "Haftalık Kürasyon • Yeni Modeller, Makaleler, Açık Kaynak ve Gelişmeler" notu.
   - Altına ince bir ayırıcı çizgi (`<hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">`).
3. Header'ın hemen altına 2 cümlelik samimi ve vizyoner bir "Haftanın Özeti" girişi yap.
4. Seçilen her gelişme için temiz bir HTML kart tasarımı (`border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px; margin-bottom: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #ffffff;`) kullan.
5. HER KARTTA SADECE ŞUNLAR YER ALMALIDIR:
   - **Başlık**: Kalın ve belirgin (ilgili model, proje veya haberin adı).
   - **Tarih & Kategori Rozetleri**:
     Başlığın hemen altında yan yana iki rozet:
     1. Tarih Rozeti: `<span style="background: #f1f5f9; padding: 3px 8px; border-radius: 4px; font-size: 12px; color: #475569; margin-right: 8px;">📅 [Yayın Tarihi]</span>` (Ham verideki tarihi birebir kullan).
     2. Kategori Rozeti: `<span style="background: #e0f2fe; padding: 3px 8px; border-radius: 4px; font-size: 12px; color: #0369a1;">[Kategori: Yeni Model / Açık Kaynak / Araştırma / Güvenlik & Olay / Endüstri]</span>`
   - **Özet**: 2-3 cümle ile ne olduğunu, modelin/olayın detayını ve teknik yönünü merak uyandırıcı, doğrudan ve net şekilde anlat.
     **KESİN KURAL:** 'Neden Önemli?' gibi ayrı bir başlık veya paragraf KESİNLİKLE EKLEME. Sadece doyurucu tek bir özet paragrafı yaz.
   - **Kaynak Butonu**: Tıklanabilir buton (`<a href="..." style="display: inline-block; margin-top: 10px; color: #2563eb; text-decoration: none; font-weight: bold; font-size: 13px;">Kaynağa Git →</a>`).
6. Sadece geçerli `<html><body style="background-color: #f8fafc; padding: 20px; font-family: sans-serif;">...</body></html>` kodunu döndür, markdown tırnakları (```html) KULLANMA.
"""


def build_prompt(items):
    raw_data = "\n".join(item.to_prompt(idx) for idx, item in enumerate(items, 1))
    return PROMPT.format(raw_data=raw_data)


def _client():
    return OpenAI(
        base_url="https://opencode.ai/zen/go/v1",
        api_key=config.OPENCODE_API_KEY,
        default_headers={"User-Agent": "newsletter-agent/1.0", "x-opencode-session": f"ses_{uuid.uuid4().hex}"},
    )


def generate_digest(items):
    """Toplanan haberlerden bülten HTML'i üretir; geçerli HTML gelene kadar birkaç kez dener."""
    log.info("OpenCode Go üzerinden bülten hazırlanıyor...")
    client = _client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_prompt(items)},
    ]

    last_error = None
    for attempt in range(1, config.LLM_MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=config.MODEL_NAME, temperature=0.2, messages=messages, timeout=180)
            content = strip_code_fences(response.choices[0].message.content or "")
            validate_digest_html(content)
            log.info("✓ Bülten HTML'i doğrulandı (deneme %d/%d).", attempt, config.LLM_MAX_ATTEMPTS)
            return content
        except Exception as e:
            last_error = e
            log.warning("[UYARI] Bülten üretimi başarısız (deneme %d/%d): %s", attempt, config.LLM_MAX_ATTEMPTS, e)
            if attempt < config.LLM_MAX_ATTEMPTS:
                wait = config.LLM_BACKOFF_SECONDS * (2 ** (attempt - 1))
                log.info("%d saniye sonra tekrar denenecek...", wait)
                time.sleep(wait)

    raise RuntimeError(f"Bülten {config.LLM_MAX_ATTEMPTS} denemede üretilemedi: {last_error}")


def strip_code_fences(content):
    """Modelin eklediği ```html tırnaklarını temizler."""
    content = content.strip()
    if content.startswith("```html"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


def validate_digest_html(content):
    """Bozuk veya eksik HTML'in abonelere gitmesini engellemek için temel kontroller."""
    lower = content.lower()
    if len(content) < 2000:
        raise ValueError(f"HTML çok kısa ({len(content)} karakter)")
    if "<html" not in lower or "</html>" not in lower:
        raise ValueError("<html> veya </html> etiketi eksik")
    if "<body" not in lower or "</body>" not in lower:
        raise ValueError("<body> veya </body> etiketi eksik (iptal bağlantısı eklenemez)")
    if lower.index("<body") > lower.index("</body>"):
        raise ValueError("<body> etiketleri sırasız")
    link_count = len(re.findall(r'<a\s[^>]*href="https?://', content, re.IGNORECASE))
    if link_count < config.MIN_DIGEST_CARDS:
        raise ValueError(f"Yalnızca {link_count} kaynak bağlantısı var (en az {config.MIN_DIGEST_CARDS} bekleniyor)")
