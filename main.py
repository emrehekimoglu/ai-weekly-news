import os
import uuid
import json
import time
import re
from datetime import datetime, timezone, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import requests
import feedparser
from openai import OpenAI

try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSPREAD = True
except ImportError:
    HAS_GSPREAD = False


# ==========================================
# 1. ORTAM DEĞİŞKENLERİ (GitHub Secrets)
# ==========================================
OPENCODE_API_KEY = os.environ.get("OPENCODE_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")

GCP_SA_KEY = os.environ.get("GCP_SA_KEY")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
WEB_APP_URL = os.environ.get("WEB_APP_URL", "")
MODEL_NAME = os.environ.get("OPENCODE_MODEL", "deepseek-v4.1-flash")

# Opsiyonel: Reddit uygulama kimlik bilgileri (yoksa top.json -> RSS denenir)
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET")
# "true" ise sadece veri toplanır; model çağrılmaz, e-posta gönderilmez
DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"


# ==========================================
# YARDIMCI: TARİH DÖNÜŞTÜRÜCÜ (TÜRKÇE)
# ==========================================
def parse_to_turkish_date(entry_or_str):
    """Farklı formatlardaki tarihleri '28 Eylül 2026' gibi temiz Türkçe formata çevirir."""
    months = [
        "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
        "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"
    ]
    try:
        # Eğer feedparser struct_time vermişse
        if hasattr(entry_or_str, "tm_year"):
            return f"{entry_or_str.tm_mday} {months[entry_or_str.tm_mon - 1]} {entry_or_str.tm_year}"
        
        # String ise
        if isinstance(entry_or_str, str) and len(entry_or_str) >= 10:
            clean_str = entry_or_str[:10]
            dt = datetime.strptime(clean_str, "%Y-%m-%d")
            return f"{dt.day} {months[dt.month - 1]} {dt.year}"
    except Exception:
        pass
    return "Bu Hafta"


# ==========================================
# 2. VERİ TOPLAMA KATMANI (6 FARKLI KAYNAK)
# ==========================================

def fetch_arxiv_papers():
    """1. arXiv Resmi Atom API: En güncel AI ve Makine Öğrenimi makaleleri."""
    print("1/6 - arXiv makaleleri taranıyor...")
    url = "https://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=8"
    feed = feedparser.parse(url)
    items = []
    
    for entry in feed.entries:
        parsed_time = entry.get("published_parsed", entry.get("updated_parsed"))
        tr_date = parse_to_turkish_date(parsed_time)

        items.append({
            "source": "arXiv",
            "title": entry.title.replace("\n", " ").strip(),
            "date": tr_date,
            "link": entry.link,
            "summary": entry.summary[:400].replace("\n", " ").strip()
        })
    return items


def fetch_hacker_news_ai():
    """2. Hacker News: Son 7 günün en çok tartışılan ve oy alan AI gelişmeleri."""
    print("2/6 - Hacker News AI trendleri taranıyor...")
    try:
        seven_days_ago = int(time.time()) - (7 * 24 * 3600)
        url = f"https://hn.algolia.com/api/v1/search_by_date?query=AI%20OR%20LLM%20OR%20Grok%20OR%20Claude%20OR%20OpenAI&tags=story&numericFilters=points>50,created_at_i>{seven_days_ago}"
        res = requests.get(url, timeout=10).json()
        
        items = []
        for hit in res.get("hits", [])[:6]:
            created_at = hit.get("created_at", "")
            tr_date = parse_to_turkish_date(created_at)

            items.append({
                "source": "Hacker News",
                "title": hit.get("title"),
                "date": tr_date,
                "link": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                "summary": f"Puan: {hit.get('points')}, Yorum: {hit.get('num_comments')}"
            })
        return items
    except Exception as e:
        print(f"Hacker News çekilirken hata: {e}")
        return []


def fetch_github_trending_ai():
    """3. GitHub Trending: Son günlerin en çok yıldız alan açık kaynak AI projeleri."""
    print("3/6 - GitHub Açık Kaynak AI projeleri taranıyor...")
    try:
        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%d')
        url = f"https://api.github.com/search/repositories?q=(topic:ai+OR+topic:llm+OR+topic:machine-learning)+language:python+created:>{seven_days_ago}&sort=stars&order=desc"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "newsletter-agent/1.0"
        }
        res = requests.get(url, headers=headers, timeout=10)
        items = []
        if res.status_code == 200:
            repos = res.json().get("items", [])[:6]
            for repo in repos:
                desc = repo.get("description") or "Açıklama belirtilmemiş."
                stars = repo.get("stargazers_count", 0)
                created_at = repo.get("created_at", "")
                tr_date = parse_to_turkish_date(created_at)
                items.append({
                    "source": "GitHub Açık Kaynak",
                    "title": f"{repo.get('full_name')} (⭐ {stars:,})",
                    "date": tr_date,
                    "link": repo.get("html_url"),
                    "summary": f"{desc} [Yıldız: {stars}]"
                })
        return items
    except Exception as e:
        print(f"GitHub çekilirken hata: {e}")
        return []


def fetch_company_blogs():
    """4. Şirket Blogları: OpenAI, Google DeepMind, Anthropic ve Hugging Face resmi duyuruları."""
    print("4/6 - Şirket blogları (OpenAI, DeepMind, Anthropic, Hugging Face) taranıyor...")
    feeds = [
        {"name": "OpenAI", "url": "https://openai.com/news/rss.xml"},
        {"name": "Google DeepMind", "url": "https://deepmind.google/blog/feed/basic/"},
        {"name": "Anthropic", "url": "https://rsshub.bestblogs.dev/anthropic/news"},
        {"name": "Hugging Face", "url": "https://huggingface.co/blog/feed.xml"}
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    items = []
    
    for f_info in feeds:
        try:
            res = requests.get(f_info["url"], headers=headers, timeout=8)
            if res.status_code == 200:
                feed = feedparser.parse(res.content)
                for entry in feed.entries[:3]:
                    parsed_time = entry.get("published_parsed", entry.get("updated_parsed"))
                    tr_date = parse_to_turkish_date(parsed_time)
                    summary = entry.get("summary", "")[:350].replace("\n", " ").strip()
                    items.append({
                        "source": f_info["name"],
                        "title": entry.title.replace("\n", " ").strip(),
                        "date": tr_date,
                        "link": entry.link,
                        "summary": summary or entry.title
                    })
        except Exception as e:
            print(f"{f_info['name']} RSS beslemesinde atlama: {e}")
            continue
            
    return items


REDDIT_USER_AGENT = "python:ai-weekly-news:v1.1 (by /u/emrehekimoglu)"


def _reddit_oauth_token():
    """REDDIT_CLIENT_ID/SECRET tanımlıysa uygulama (app-only) OAuth token'ı alır."""
    if not (REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET):
        return None
    try:
        res = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": REDDIT_USER_AGENT},
            timeout=8,
        )
        res.raise_for_status()
        return res.json().get("access_token")
    except Exception as e:
        print(f"Reddit OAuth token alınamadı: {e}")
        return None


def _reddit_posts_json(sub, token):
    """top.json listesini çeker; JSON dönmezse (IP engeli vb.) None döner."""
    headers = {"User-Agent": REDDIT_USER_AGENT}
    if token:
        url = f"https://oauth.reddit.com/r/{sub}/top?t=week&limit=6&raw_json=1"
        headers["Authorization"] = f"Bearer {token}"
    else:
        url = f"https://www.reddit.com/r/{sub}/top.json?t=week&limit=6&raw_json=1"
    res = requests.get(url, headers=headers, timeout=8)
    if res.status_code != 200 or "json" not in res.headers.get("Content-Type", ""):
        print(f"Reddit r/{sub} JSON erişimi reddedildi (HTTP {res.status_code}, {res.headers.get('Content-Type', '?')})")
        return None
    return [p.get("data", {}) for p in res.json().get("data", {}).get("children", [])]


def _reddit_items_rss(sub):
    """JSON engellendiğinde haftalık top RSS akışına düşer (upvote bilgisi yok, sıralama zaten skora göre)."""
    res = requests.get(
        f"https://www.reddit.com/r/{sub}/top/.rss?t=week&limit=5",
        headers={"User-Agent": REDDIT_USER_AGENT},
        timeout=8,
    )
    if res.status_code != 200:
        print(f"Reddit r/{sub} RSS erişimi reddedildi (HTTP {res.status_code})")
        return []
    feed = feedparser.parse(res.content)
    items = []
    for entry in feed.entries[:5]:
        content = entry.get("content", [{}])[0].get("value", "") or entry.get("summary", "")
        text = re.sub(r"<[^>]+>", " ", content).replace("submitted by", "")
        text = re.sub(r"\s+", " ", text).strip()[:300]
        items.append({
            "source": f"Reddit r/{sub}",
            "title": entry.title,
            "date": parse_to_turkish_date(entry.get("updated_parsed", entry.get("published_parsed"))),
            "link": entry.link,
            "summary": f"[Haftanın En Çok Oylanan Paylaşımı] {text}"
        })
    return items


def fetch_reddit_viral_ai():
    """5. Reddit Toplulukları: r/ChatGPT, r/singularity ve r/LocalLLaMA viral olayları, jailbreak ve skandallar.

    Reddit, GitHub Actions gibi veri merkezi IP'lerinden gelen kimliksiz .json isteklerini
    HTML engel sayfasıyla yanıtlıyor. Sıra: OAuth (secret varsa) -> top.json -> RSS.
    """
    print("5/6 - Reddit viral AI olayları ve tartışmaları taranıyor...")
    subreddits = ["ChatGPT", "singularity", "LocalLLaMA"]
    token = _reddit_oauth_token()
    items = []
    
    for sub in subreddits:
        try:
            posts = _reddit_posts_json(sub, token)
            if posts is None:
                rss_items = _reddit_items_rss(sub)
                print(f"Reddit r/{sub}: RSS üzerinden {len(rss_items)} içerik alındı.")
                items.extend(rss_items)
                continue
            for pdata in posts:
                # Sadece toplulukta yüksek ilgi (300+ upvote) görmüş içerikler
                if pdata.get("score", 0) > 300:
                    created_utc = pdata.get("created_utc", 0)
                    dt = datetime.fromtimestamp(created_utc)
                    tr_date = parse_to_turkish_date(dt.strftime("%Y-%m-%d"))
                    
                    selftext = pdata.get("selftext", "")[:300].replace("\n", " ").strip()
                    items.append({
                        "source": f"Reddit r/{sub}",
                        "title": pdata.get("title"),
                        "date": tr_date,
                        "link": f"https://reddit.com{pdata.get('permalink')}",
                        "summary": f"[Viral Paylaşım - {pdata.get('score')} Upvote, {pdata.get('num_comments')} Yorum] {selftext}"
                    })
        except Exception as e:
            print(f"Reddit r/{sub} taranırken hata: {e}")
            continue
    print(f"Reddit toplam {len(items)} içerik.")
    return items


def fetch_tech_media_ai():
    """6. Bağımsız Teknoloji Medyası: The Verge ve Ars Technica (Model lansmanları, davalar, regülasyonlar)."""
    print("6/6 - Bağımsız teknoloji basını (The Verge, Ars Technica) taranıyor...")
    feeds = [
        {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
        {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/technology-lab"}
    ]
    items = []
    for f in feeds:
        try:
            feed = feedparser.parse(f["url"])
            for entry in feed.entries[:4]:
                parsed_time = entry.get("published_parsed", entry.get("updated_parsed"))
                tr_date = parse_to_turkish_date(parsed_time)
                items.append({
                    "source": f["name"],
                    "title": entry.title,
                    "date": tr_date,
                    "link": entry.link,
                    "summary": entry.get("summary", "")[:350].replace("\n", " ").strip()
                })
        except Exception:
            continue
    return items


# ==========================================
# 3. AKTİF & TEKİL ABONELERİ ÇEKME
# ==========================================
def get_subscribers():
    """Google Sheets üzerinden durumu 'AKTIF' olan kişileri tekilleştirerek çeker."""
    if HAS_GSPREAD and GCP_SA_KEY and SPREADSHEET_ID:
        try:
            print("Google Sheets tablosuna bağlanılıyor...")
            sa_creds = json.loads(GCP_SA_KEY)
            scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
            creds = Credentials.from_service_account_info(sa_creds, scopes=scopes)
            gc = gspread.authorize(creds)
            
            sheet = gc.open_by_key(SPREADSHEET_ID).sheet1
            rows = sheet.get_all_values()
            
            active_subscribers = []
            seen_emails = set()
            
            # En yeni kayıttan eskiye doğru tara
            for row in reversed(rows[1:]):
                if len(row) >= 4:
                    email = row[1].strip().lower()
                    status = row[2].strip().upper()
                    token = row[3].strip()
                    
                    if email in seen_emails:
                        continue
                    
                    if status == "AKTIF" and "@" in email:
                        active_subscribers.append({"email": email, "token": token})
                        seen_emails.add(email)

            if active_subscribers:
                print(f"✓ Toplam {len(active_subscribers)} TEKİL aktif abone bulundu.")
                return active_subscribers
            else:
                print("[UYARI] Tabloda 'AKTIF' statüsünde abone bulunamadı!")

        except Exception as e:
            print(f"[HATA] Google Sheets okunurken hata: {e}")

    # subscribers.txt kontrolü
    if os.path.exists("subscribers.txt"):
        emails = []
        seen = set()
        with open("subscribers.txt", "r", encoding="utf-8") as f:
            for line in f:
                em = line.strip().lower()
                if "@" in em and not em.startswith("#") and em not in seen:
                    emails.append({"email": em, "token": ""})
                    seen.add(em)
        if emails:
            return emails

    return [{"email": EMAIL_RECEIVER, "token": ""}] if EMAIL_RECEIVER else []


# ==========================================
# 4. LLM BÜLTEN ÜRETİMİ (ÖNCELİKLİ SEÇİM)
# ==========================================
def generate_digest_with_opencode(raw_data):
    """Toplanan tüm verileri analiz edip şık bir HTML bülten üretir."""
    print("OpenCode Go üzerinden bülten hazırlanıyor...")

    session_id = f"ses_{uuid.uuid4().hex}"

    client = OpenAI(
        base_url="https://opencode.ai/zen/go/v1",
        api_key=OPENCODE_API_KEY,
        default_headers={
            "User-Agent": "newsletter-agent/1.0",
            "x-opencode-session": session_id
        }
    )

    prompt = f"""
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
   - Yuvarlak yapay zekâ ikonu: `<img src="https://cdn-icons-png.flaticon.com/512/4712/4712109.png" width="44" height="44" style="vertical-align: middle; margin-right: 12px; border-radius: 50%;">`
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

    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0.2,
        messages=[
            {"role": "system", "content": "Sen profesyonel bir teknoloji bülteni editörüsün."},
            {"role": "user", "content": prompt}
        ]
    )

    content = response.choices[0].message.content.strip()
    if content.startswith("```html"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


# ==========================================
# 5. E-POSTA DAĞITIMI
# ==========================================
def send_newsletter_to_all(html_content, recipients):
    """Bülteni her aboneye kendi kişisel iptal bağlantısıyla postalar."""
    if not recipients:
        print("Gönderilecek abone bulunamadı!")
        return

    print(f"Toplam {len(recipients)} kişiye e-posta gönderimi başlıyor...")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)

        for sub in recipients:
            email = sub["email"]
            token = sub.get("token", "")
            
            try:
                unsub_url = f"{WEB_APP_URL}?action=unsubscribe&email={email}&token={token}" if WEB_APP_URL and token else "#"
                
                footer_html = f"""
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0 15px 0;">
                <p style="text-align: center; font-size: 12px; color: #94a3b8; font-family: sans-serif;">
                  Bu bülteni AI & Teknoloji Radarı'na abone olduğunuz için alıyorsunuz.<br>
                  Abonelikten ayrılmak isterseniz <a href="{unsub_url}" style="color: #64748b; text-decoration: underline;">buraya tıklayabilirsiniz</a>.
                </p>
                """
                personalized_html = html_content.replace("</body>", f"{footer_html}</body>")

                msg = MIMEMultipart("alternative")
                msg["Subject"] = "🚀 Haftalık Yapay Zekâ & Teknoloji Radarı"
                msg["From"] = formataddr(("🤖 AI & Teknoloji Radarı", EMAIL_SENDER))
                msg["To"] = email

                part = MIMEText(personalized_html, "html")
                msg.attach(part)

                server.sendmail(EMAIL_SENDER, email, msg.as_string())
                print(f"✓ Başarıyla gönderildi: {email}")
                time.sleep(1)

            except Exception as e:
                print(f"✗ Hata ({email}): {e}")

    print("Tüm gönderimler başarıyla tamamlandı!")


# ==========================================
# 6. ANA YÜRÜTME DÖNGÜSÜ
# ==========================================
def main():
    # 6 ana kaynaktan veri topla
    arxiv_data = fetch_arxiv_papers()
    hn_data = fetch_hacker_news_ai()
    github_data = fetch_github_trending_ai()
    company_data = fetch_company_blogs()
    reddit_data = fetch_reddit_viral_ai()
    media_data = fetch_tech_media_ai()
    
    all_data = arxiv_data + hn_data + github_data + company_data + reddit_data + media_data

    if not all_data:
        print("Hiçbir kaynaktan veri toplanamadı!")
        return

    if DRY_RUN:
        print(f"DRY_RUN: Toplam {len(all_data)} içerik toplandı (Reddit: {len(reddit_data)}). Model ve e-posta atlandı.")
        for item in reddit_data:
            print(f"  - [{item['source']}] {item['title']}")
        return

    print(f"Toplam {len(all_data)} adet aday içerik toplandı. Modele aktarılıyor...")

    raw_text = ""
    for idx, item in enumerate(all_data, 1):
        raw_text += f"[{idx}] Kaynak: {item['source']}\nBaşlık: {item['title']}\nYayın Tarihi: {item['date']}\nLink: {item['link']}\nÖzet: {item['summary']}\n\n"

    newsletter_html = generate_digest_with_opencode(raw_text)
    recipients = get_subscribers()
    send_newsletter_to_all(newsletter_html, recipients)


if __name__ == "__main__":
    main()
