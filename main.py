import os
import uuid
import json
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import requests
import feedparser
from openai import OpenAI

# Google Sheets entegrasyonu için (isteğe bağlı/kurulduysa çalışır)
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
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")  # Yedek / varsayılan alıcı

# Google Sheets anahtarları (Form bağlandıysa kullanılır)
GCP_SA_KEY = os.environ.get("GCP_SA_KEY")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

# Kullanılacak model (OpenCode Go üzerindeki en iyi Türkçe ve akıl yürütme modeli)
MODEL_NAME = os.environ.get("OPENCODE_MODEL", "qwen3.8-max")


# ==========================================
# 2. VERİ TOPLAMA FONKSİYONLARI
# ==========================================
def fetch_arxiv_papers():
    """arXiv cs.AI (Yapay Zeka) ve cs.LG (Makine Öğrenimi) son makalelerini çeker."""
    print("arXiv makaleleri toplanıyor...")
    urls = [
        "https://export.arxiv.org/rss/cs.AI",
        "https://export.arxiv.org/rss/cs.LG",
    ]
    items = []
    for url in urls:
        feed = feedparser.parse(url)
        for entry in feed.entries[:8]:
            items.append({
                "source": "arXiv",
                "title": entry.title,
                "link": entry.link,
                "summary": entry.summary[:400]
            })
    return items


def fetch_hacker_news_ai():
    """Hacker News üzerinde son günlerin çok oy alan AI haberlerini çeker."""
    print("Hacker News trendleri toplanıyor...")
    try:
        url = "https://hn.algolia.com/api/v1/search?query=AI%20LLM&tags=story&numericFilters=points>120"
        res = requests.get(url, timeout=10).json()
        items = []
        for hit in res.get("hits", [])[:8]:
            items.append({
                "source": "Hacker News",
                "title": hit.get("title"),
                "link": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                "summary": f"Puan: {hit.get('points')}, Yorum: {hit.get('num_comments')}"
            })
        return items
    except Exception as e:
        print(f"Hacker News çekilirken hata: {e}")
        return []


# ==========================================
# 3. ABONE LİSTESİNİ ALMA
# ==========================================
def get_subscribers():
    """
    Abone listesini belirler:
    1. Google Sheets bağlıysa oradaki form yanıtlarından çeker.
    2. subscribers.txt dosyası varsa oradan okur.
    3. Hiçbiri yoksa varsayılan olarak EMAIL_RECEIVER adresine gönderir.
    """
    # 1. Google Sheets Denemesi
    if HAS_GSPREAD and GCP_SA_KEY and SPREADSHEET_ID:
        try:
            print("Google Sheets üzerinden abone listesi çekiliyor...")
            sa_creds = json.loads(GCP_SA_KEY)
            scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
            creds = Credentials.from_service_account_info(sa_creds, scopes=scopes)
            gc = gspread.authorize(creds)
            
            sheet = gc.open_by_key(SPREADSHEET_ID).sheet1
            records = sheet.get_all_values()
            
            if len(records) > 1:
                # E-posta sütununu akıllıca tespit et
                header = [str(col).lower() for col in records[0]]
                email_col_idx = 1  # Form yanıtlarında varsayılan 2. sütundur
                for idx, col_name in enumerate(header):
                    if "posta" in col_name or "email" in col_name or "mail" in col_name:
                        email_col_idx = idx
                        break

                emails = []
                for row in records[1:]:
                    if len(row) > email_col_idx:
                        email = row[email_col_idx].strip()
                        if "@" in email and email not in emails:
                            emails.append(email)

                if emails:
                    print(f"✓ Google Sheets'ten {len(emails)} abone alındı.")
                    return emails
        except Exception as e:
            print(f"Google Sheets okunurken hata oluştu: {e}")

    # 2. Yerel subscribers.txt Denemesi
    if os.path.exists("subscribers.txt"):
        print("subscribers.txt dosyasından aboneler okunuyor...")
        emails = []
        with open("subscribers.txt", "r", encoding="utf-8") as f:
            for line in f:
                email = line.strip()
                if email and not email.startswith("#") and "@" in email:
                    emails.append(email)
        if emails:
            return emails

    # 3. Yedek (Kişisel Alıcı)
    print("Özel liste bulunamadı, varsayılan alıcı kullanılıyor.")
    return [EMAIL_RECEIVER] if EMAIL_RECEIVER else []


# ==========================================
# 4. OPENCODE GO İLE BÜLTEN ÜRETİMİ
# ==========================================
def generate_digest_with_opencode(raw_data):
    """OpenCode Go API'sini kullanarak HTML bülteni üretir."""
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
Sen dünya standartlarında bir yapay zeka ve teknoloji baş editörüsün.
Aşağıda son bir haftada yayımlanan ham teknoloji ve araştırma içerikleri yer alıyor:

{raw_data}

GÖREVİN:
Bu verileri filtreleyerek gerçekten çığır açıcı, sektörde ses getirebilecek veya yeni bir paradigma başlatan EN ÖNEMLİ 5-7 gelişmeyi seç.
Bunu bir e-posta bülteni olarak, modern, temiz ve profesyonel bir HTML formatında yaz.

ŞABLON KURALLARI:
1. Türkçe yaz.
2. EN ÜSTE ŞIK BİR HEADER (BAŞLIK & LOGO) ALANI EKLE:
   - Modern bir bülten başlığı oluştur:
     - Yuvarlak bir yapay zekâ ikonu kullan: `<img src="https://cdn-icons-png.flaticon.com/512/4712/4712109.png" width="44" height="44" style="vertical-align: middle; margin-right: 12px; border-radius: 50%;">`
     - İkonun yanına kalın, koyu renkli ve modern fontla "AI & TEKNOLOJİ RADARI" yaz.
     - Altına küçük ve gri fontla "Haftalık Kürasyon • Yeni Modeller, Makaleler ve Gelişmeler" notunu ekle.
     - Altına ince bir ayırıcı çizgi (`<hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">`) çek.
3. Header'ın hemen altına 2 cümlelik samimi ve vizyoner bir "Haftanın Özeti" girişi yap.
4. Seçilen her gelişme için temiz bir HTML kart tasarımı (`border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px; margin-bottom: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #ffffff;`) kullan.
5. Her kartta şunlar bulunsun:
   - **Başlık**: Kalın ve belirgin (varsa ilgili model/teknoloji adı)
   - **Kategori Etiketi**: Şık bir rozet (badge) gibi görünen renkli etiket (Yeni Model, Araştırma/Makale, Açık Kaynak, Endüstri)
   - **Özet**: 2-3 cümle ile ne yapıldığını ve teknik yeniliği açıkla.
   - **Neden Önemli?**: Sektöre ve geleceğe etkisini 1-2 cümleyle açıkla.
   - **Kaynak Linki**: Doğrudan tıklanabilir bir buton veya link formatında kaynak URL'si (`<a href="..." style="color: #2563eb; text-decoration: none; font-weight: bold;">Kaynağa Git →</a>`).
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
    
    # Model fazladan markdown blokları eklediyse temizle
    if content.startswith("```html"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


# ==========================================
# 5. E-POSTA DAĞITIM FONKSİYONU
# ==========================================
def send_newsletter_to_all(html_content, recipients):
    """Bülteni tek bir SMTP oturumu üzerinden tüm abonelere tek tek gönderir."""
    if not recipients:
        print("Gönderilecek alıcı bulunamadı!")
        return

    print(f"Toplam {len(recipients)} aboneye e-posta gönderimi başlıyor...")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)

        for email in recipients:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = "🚀 Haftalık Yapay Zekâ & Teknoloji Radarı"
                msg["From"] = formataddr(("🤖 AI & Teknoloji Radarı", EMAIL_SENDER))
                msg["To"] = email  # Sadece alıcının kendi adresi görünür

                part = MIMEText(html_content, "html")
                msg.attach(part)

                server.sendmail(EMAIL_SENDER, email, msg.as_string())
                print(f"✓ Gönderildi: {email}")
                
                # Gmail spam filtresine takılmamak için 1 saniye bekle
                time.sleep(1)

            except Exception as e:
                print(f"✗ Hata ({email}): {e}")

    print("Tüm e-postalar başarıyla postalandı!")


# ==========================================
# 6. ANA YÜRÜTME DÖNGÜSÜ
# ==========================================
def main():
    # 1. Kaynaklardan veri topla
    arxiv_data = fetch_arxiv_papers()
    hn_data = fetch_hacker_news_ai()
    all_data = arxiv_data + hn_data

    if not all_data:
        print("Hiçbir veri toplanamadı!")
        return

    # 2. Metin formatına çevir
    raw_text = ""
    for idx, item in enumerate(all_data, 1):
        raw_text += f"[{idx}] Kaynak: {item['source']}\nBaşlık: {item['title']}\nLink: {item['link']}\nÖzet: {item['summary']}\n\n"

    # 3. OpenCode Go modeline özetlet
    newsletter_html = generate_digest_with_opencode(raw_text)

    # 4. Aboneleri belirle ve gönder
    recipients = get_subscribers()
    send_newsletter_to_all(newsletter_html, recipients)


if __name__ == "__main__":
    main()
