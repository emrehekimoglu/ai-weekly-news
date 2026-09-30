"""OpenCode Go üzerinden LLM ile haftanın seçkisi (JSON) ve doğrulaması."""

import json
import logging
import time
import uuid

from openai import OpenAI

from newsletter import config
from newsletter.models import Digest, DigestEntry, Stat

log = logging.getLogger(__name__)

SYSTEM_PROMPT = "Sen profesyonel bir teknoloji bülteni editörüsün."

CATEGORIES = ["Yeni Model", "Açık Kaynak", "Araştırma", "Güvenlik & Olay", "Endüstri"]
MAX_DIGEST_CARDS = 12
MAX_HEADLINE_CHARS = 90
MAX_TLDR_CHARS = 160
MAX_STAT_VALUE_CHARS = 16

PROMPT = """
Sen dünya standartlarında kıdemli bir yapay zeka ve teknoloji baş editörüsün.
Aşağıda son bir haftada yayımlanan ham teknoloji haberleri, makaleler, model duyuruları ve viral topluluk tartışmaları numaralı olarak yer alıyor:

{raw_data}

GÖREVİN:
Bu verileri titizlikle filtreleyerek haftanın EN ÖNEMLİ 10 gelişmesini seç.
(Eğer bu hafta gerçekten kaçırılmaması gereken çok kritik gelişmeler olduysa en fazla 12'ye kadar esneyebilirsin; yani toplam 10 ila 12 madde seç).
Aynı olayı anlatan birden fazla kayıt varsa sadece en iyi kaynağı seç.
{previous}
İÇERİK SEÇİMİNDE ÖNCELİK SIRAN (ÇOK ÖNEMLİ):
1. YENİ MODEL LANSMANLARI: Yeni bir GPT, Claude, Gemini, Grok, Llama veya güçlü açık kaynak model duyurulduysa MUTLAKA İLK SIRALARDA YER VER.
2. VİRAL / SKANDAL / GÜVENLİK OLAYLARI: Modellerin beklenmedik/çıldıran davranışları, güvenlik filtrelerinin çökmesi (jailbreak), sansür tartışmaları veya büyük şirket krizleri varsa MUTLAKA BÜLTENE DAHİL ET.
3. ÇIĞIR AÇICI ARAŞTIRMALAR & AÇIK KAYNAK: Yeni bir mimari öneren akademik çalışmalar ve GitHub'da patlayan açık kaynak projeler.

YAZIM KURALLARI:
- Her şeyi Türkçe yaz.
- "headline": Haftanın manşeti. En çarpıcı gelişmeyi anlatan, dergi kapağı gibi merak uyandıran 3-8 kelimelik bir başlık (soru da olabilir). E-postanın konu satırı da budur. Abartma, verilerde olmayan bir iddia EKLEME.
- "intro": 2 cümlelik samimi ve vizyoner bir "Haftanın Özeti" girişi.
- "tldr": "30 saniyede bu hafta" için tam 3 madde; her biri tek cümle ve en fazla 120 karakter. Haftanın en önemli üç gelişmesini, okumaya vakti olmayan birine anlatır gibi yaz.
- "stat": "Haftanın Rakamı". Seçtiğin haberlerden birinde AÇIKÇA geçen çarpıcı bir sayı: {{"value": "10 GW", "label": "Bu sayının ne anlama geldiğini anlatan tek cümle."}}. "value" en fazla 12 karakter olsun (örn. "%40", "128K", "3 kat"). Ham veride böyle bir sayı yoksa null yaz; ASLA sayı uydurma.
- Her seçilen madde için:
  - "id": Ham verideki köşeli parantez içindeki numara (tam sayı). Bağlantı ve tarih bu numaradan alınır, kendin bağlantı YAZMA.
  - "title": Kısa ve belirgin başlık (ilgili model, proje veya haberin adı).
  - "category": Şunlardan biri: {categories}
  - "summary": 2-3 cümle ile ne olduğunu, modelin/olayın detayını ve teknik yönünü merak uyandırıcı, doğrudan ve net şekilde anlat. 'Neden Önemli?' gibi ayrı bir bölüm EKLEME.
- Maddeleri önem sırasına göre diz.

ÇIKTI BİÇİMİ:
Sadece aşağıdaki yapıda geçerli bir JSON nesnesi döndür; HTML, markdown veya açıklama EKLEME:
{{"headline": "...", "intro": "...", "tldr": ["...", "...", "..."], "stat": {{"value": "...", "label": "..."}}, "items": [{{"id": 3, "title": "...", "category": "Yeni Model", "summary": "..."}}]}}
"""


PREVIOUS = """
Aşağıdaki konular son sayılarda zaten işlendi. Aynı olayı TEKRAR SEÇME; ancak önemli yeni bir gelişme varsa (örneğin duyurulan modelin yayınlanması) seçebilirsin:
{titles}
"""


def build_prompt(items, previous_titles=()):
    raw_data = "\n".join(item.to_prompt(idx) for idx, item in enumerate(items, 1))
    previous = PREVIOUS.format(titles="\n".join(f"- {t}" for t in previous_titles)) if previous_titles else ""
    return PROMPT.format(raw_data=raw_data, categories=" / ".join(CATEGORIES), previous=previous)


def _client():
    return OpenAI(
        base_url="https://opencode.ai/zen/go/v1",
        api_key=config.OPENCODE_API_KEY,
        default_headers={"User-Agent": "newsletter-agent/1.0", "x-opencode-session": f"ses_{uuid.uuid4().hex}"},
    )


def generate_digest(items, previous_titles=()):
    """Modelden haftanın seçkisini JSON olarak alır; geçerli yanıt gelene kadar birkaç kez dener."""
    log.info("OpenCode Go üzerinden bülten hazırlanıyor...")
    client = _client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_prompt(items, previous_titles)},
    ]

    last_error = None
    for attempt in range(1, config.LLM_MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=config.MODEL_NAME, temperature=0.2, messages=messages, timeout=180)
            digest = parse_digest(response.choices[0].message.content or "", items)
            log.info("✓ Bülten seçkisi doğrulandı: %d haber (deneme %d/%d).",
                     len(digest.entries), attempt, config.LLM_MAX_ATTEMPTS)
            return digest
        except Exception as e:
            last_error = e
            log.warning("[UYARI] Bülten üretimi başarısız (deneme %d/%d): %s", attempt, config.LLM_MAX_ATTEMPTS, e)
            if attempt < config.LLM_MAX_ATTEMPTS:
                wait = config.LLM_BACKOFF_SECONDS * (2 ** (attempt - 1))
                log.info("%d saniye sonra tekrar denenecek...", wait)
                time.sleep(wait)

    raise RuntimeError(f"Bülten {config.LLM_MAX_ATTEMPTS} denemede üretilemedi: {last_error}")


def extract_json(content):
    """Yanıttaki JSON nesnesini çıkarır (```json tırnakları veya öncesindeki/sonrasındaki metin atlanır)."""
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end < start:
        raise ValueError("Yanıtta JSON nesnesi yok")
    try:
        return json.loads(content[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"Geçersiz JSON: {e}") from e


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{field}' boş veya metin değil")
    return " ".join(value.split())


def parse_digest(content, items):
    """Model yanıtını doğrulayıp Digest'e çevirir; bozuk yanıtın abonelere gitmesini engeller.

    Bağlantı ve tarih her zaman kaynak öğeden alınır; modelin uydurduğu bağlantı bültene giremez.
    """
    data = extract_json(content)
    if not isinstance(data, dict):
        raise ValueError("JSON bir nesne değil")
    intro = _text(data.get("intro"), "intro")
    picks = data.get("items")
    if not isinstance(picks, list):
        raise ValueError("'items' listesi yok")

    entries, seen = [], set()
    for pick in picks:
        if not isinstance(pick, dict):
            raise ValueError("'items' içinde nesne olmayan öğe var")
        idx = pick.get("id")
        if isinstance(idx, str) and idx.strip().isdigit():
            idx = int(idx)
        if not isinstance(idx, int) or not 1 <= idx <= len(items):
            raise ValueError(f"Geçersiz haber numarası: {idx!r}")
        if idx in seen:
            continue
        seen.add(idx)
        category = pick.get("category")
        if category not in CATEGORIES:
            log.warning("Bilinmeyen kategori %r, 'Endüstri' kullanıldı", category)
            category = "Endüstri"
        entries.append(DigestEntry(
            item=items[idx - 1],
            title=_text(pick.get("title"), "title"),
            category=category,
            summary=_text(pick.get("summary"), "summary"),
        ))

    if len(entries) < config.MIN_DIGEST_CARDS:
        raise ValueError(f"Yalnızca {len(entries)} haber seçilmiş (en az {config.MIN_DIGEST_CARDS} bekleniyor)")
    return Digest(intro=intro, entries=entries[:MAX_DIGEST_CARDS], headline=_headline(data.get("headline")),
                  tldr=_tldr(data.get("tldr")), stat=_stat(data.get("stat")))


def _optional_text(value, max_chars):
    """Kapak alanları için: geçerli kısa metin veya None (bozuk alan bülteni durdurmaz, sadece atlanır)."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text if text and len(text) <= max_chars else None


def _headline(value):
    headline = _optional_text(value, MAX_HEADLINE_CHARS)
    if value is not None and headline is None:
        log.warning("Manşet geçersiz veya çok uzun, atlandı: %r", value)
    return headline


def _tldr(value):
    if not isinstance(value, list):
        if value is not None:
            log.warning("'tldr' liste değil, atlandı")
        return []
    points = [p for p in (_optional_text(v, MAX_TLDR_CHARS) for v in value) if p][:3]
    if len(points) < 2:
        log.warning("'tldr' için yeterli geçerli madde yok, bölüm atlandı")
        return []
    return points


def _stat(value):
    if value is None:
        return None
    if isinstance(value, dict):
        number = _optional_text(value.get("value"), MAX_STAT_VALUE_CHARS)
        label = _optional_text(value.get("label"), MAX_TLDR_CHARS * 2)
        if number and label and any(ch.isdigit() for ch in number):
            return Stat(value=number, label=label)
    log.warning("'stat' geçersiz, 'Haftanın Rakamı' bölümü atlandı: %r", value)
    return None
