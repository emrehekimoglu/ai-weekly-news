import os
import uuid
import json
import time
import re
from datetime import datetime
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
# 1. ORTAM DEĞİŞKENLERİ
# ==========================================
OPENCODE_API_KEY = os.environ.get("OPENCODE_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")

GCP_SA_KEY = os.environ.get("GCP_SA_KEY")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
MODEL_NAME = os.environ.get("OPENCODE_MODEL", "qwen3.8-max")


# ==========================================
# 2. VERİ TOPLAMA (TARİHLERLE BİRLİKTE)
# ==========================================
def fetch_arxiv_papers():
    """arXiv makalelerini başlık, özet ve yayın tarihiyle çeker."""
    print("arXiv makaleleri toplanıyor...")
    urls = [
        "https://export.arxiv.org/rss/cs.AI",
        "https://export.arxiv.org/rss/cs.LG",
    ]
    items = []
    for url in urls:
        feed = feedparser.parse(url)
        for entry in feed.entries[:8]:
            # Tarih bilgisini al
            raw_date = entry.get("published", entry.get("updated", ""))
            clean_date = raw_date[:10] if raw_date else datetime.now().strftime("%Y-%m-%d")
            
            items.append({
                "source": "arXiv",
                "title": entry.title.replace("\n", " ").strip(),
                "date": clean_date,
                "link": entry.link,
                "summary": entry.summary[:400].replace("\n", " ").strip()
            })
    return items


def fetch_hacker_news_ai():
    """Hacker News popüler AI haberlerini tarihiyle çeker."""
    print("Hacker News trendleri toplanıyor...")
    try:
        url = "https://hn.algolia.com/api/v1/search?query=AI%20LLM&tags=story&numericFilters=points>120"
        res = requests.get(url, timeout=10).json()
        items = []
        for hit in res.get("hits", [])[:8]:
            created_at = hit.get("created_at", "")
            clean_date = created_at[:10] if created_at else datetime.now().strftime("%Y-%m-%d")
            
            items.append({
                "source": "Hacker News",
                "title": hit.get("title"),
                "date": clean_date,
                "link": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                "summary": f"Puan: {hit.get('points')}, Yorum: {hit.get('num_comments')}"
            })
        return items
    except Exception as e:
        print(f"Hacker News çekilirken hata: {e}")
        return []


# ==========================================
# 3. ABONE LİSTESİNİ ÇEKME (GELİŞMİŞ)
# ==========================================
def get_subscribers():
    """Google Sheets tablosunu tarayıp aboneleri tespit eder."""
    # Kontrol logları (Sorun olursa doğrudan terminalde görünür)
    if not HAS_GSPREAD:
        print("[HATA] gspread kütüphanesi kurulu değil! requirements.txt dosyasını kontrol edin.")
    if not GCP_SA_KEY:
        print("[UYARI] GCP_SA_KEY ortam değişkeni boş! newsletter.yml dosyasındaki env: kısmını kontrol edin.")
    if not SPREADSHEET_ID:
        print("[UYARI] SPREADSHEET_ID ortam değişkeni boş! newsletter.yml dosyasındaki env: kısmını kontrol edin.")

    if HAS_GSPREAD and GCP_SA_KEY and SPREADSHEET_ID:
        try:
            print("Google Sheets tablosuna bağlanılıyor...")
            sa_creds = json.loads(GCP_SA_KEY)
            scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
            creds = Credentials.from_service_account_info(sa_creds, scopes=scopes)
            gc = gspread.authorize(creds)
            
            sheet = gc.open_by_key(SPREADSHEET_ID).sheet1
            all_cells = sheet.get_all_values()
            
            emails = []
            email_pattern = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")

            # İlk satır (başlıklar) hariç tüm hücreleri tara
            for row in all_cells[1:]:
                for cell in row:
                    val = cell.strip()
                    if email_pattern.match(val) and val not in emails:
                        emails.append(val)

            if emails:
                print(f"✓ Başarılı: Google Sheets üzerinden {len(emails)} abone bulundu: {emails}")
                return emails
            else:
                print("[UYARI] Tabloya bağlandı ancak içinde e-posta formatında veri bulunamadı!")

        except Exception as e:
            print(f"[HATA] Google Sheets okunurken istisna oluştu: {e}")

    # subscribers.txt kontrolü
    if os.path.exists("subscribers.txt"):
        print("subscribers.txt okunuyor...")
        emails = []
        with open("subscribers.txt", "r", encoding="utf-8") as f:
            for line in f:
                em = line.strip()
                if "@" in em and not em.startswith("#") and em not in emails:
                    emails.append(em)
        if emails:
            return emails

    print("Özel listeden sonuç alınamadı. Varsayılan e-posta adresine gönderilecek.")
    return [EMAIL_RECEIVER] if EMAIL_RECEIVER else []


# ==========================================
# 4. TARİHLİ BÜLTEN ÜRETİMİ
# ==========================================
def generate_digest_with_opencode(raw_data):
    """HTML formatında tarihli bülten üretir."""
    print("OpenCode Go üzerinden model bülteni hazırlıyor...")

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
Aşağıda son bir haftada yayımlanan ham teknoloji ve araştırma içerikleri (tarihleriyle birlikte) yer alıyor:

{raw_data}

GÖREVİN:
Bu verileri filtreleyerek gerçekten çığır açıcı, sektörde ses getirebilecek veya yeni bir paradigma başlatan EN ÖNEMLİ 5-7 gelişmeyi seç.
Bunu bir e-posta bülteni olarak modern, temiz ve profesyonel bir HTML formatında yaz.

ŞABLON KURALLARI:
1. Türkçe yaz.
2. EN ÜSTE ŞIK BİR HEADER ALANI EKLE:
   - Yuvarlak yapay zekâ ikonu: `<img src="https://cdn-icons-png.flaticon.com/512/4712/4712109.png" width="44" height="44" style="vertical-align: middle; margin-right: 12px; border-radius: 50%;">`
   - Yanına kalın harflerle "AI & TEKNOLOJİ RADARI" başlığı.
   - Altına gri ve küçük puntolarla "Haftalık Kürasyon • Yeni Modeller, Makaleler ve Gelişmeler" yazısı.
   - Altına ince bir ayırıcı çizgi (`<hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">`).
3. Header'ın hemen altına 2 cümlelik samimi ve vizyoner bir "Haftanın Özeti" girişi yap.
4. Seçilen her gelişme için temiz bir HTML kart tasarımı (`border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px; margin-bottom: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #ffffff;`) kullan.
5. HER KARTTA ZORUNLU BULUNMASI GEREKENLER:
   - **Başlık**: Kalın ve belirgin (varsa ilgili model/teknoloji adı).
   - **Tarih & Kategori**: Başlığın hemen altında yan yana küçük gri rozetler halinde yer alsın. (Örn: `<span style="background: #f1f5f9; padding: 3px 8px; border-radius: 4px; font-size: 12px; color: #475569; margin-right: 8px;">📅 [Yayın/Duyuru Tarihi]</span> <span style="background: #e0f2fe; padding: 3px 8px; border-radius: 4px; font-size: 12px; color: #0369a1;">[Kategori: Yeni Model / Makale / Endüstri]</span>`)
   - **Özet**: 2-3 cümle ile ne yapıldığını ve teknik yeniliği açıkla.
   - **Neden Önemli?**: Sektöre ve geleceğe etkisini 1-2 cümleyle açıkla.
   - **Kaynak Butonu**: Tıklanabilir kaynak linki (`<a href="..." style="display: inline-block; margin-top: 8px; color: #2563eb; text-decoration: none; font-weight: bold; font-size: 13px;">Kaynağa Git →</a>`).
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
    """Bülteni abonelere gönderir."""
    if not recipients:
        print("Gönderilecek alıcı bulunamadı!")
        return

    print(f"Toplam {len(recipients)} kişiye e-posta gönderimi başlıyor...")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)

        for email in recipients:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = "🚀 Haftalık Yapay Zekâ & Teknoloji Radarı"
                msg["From"] = formataddr(("🤖 AI & Teknoloji Radarı", EMAIL_SENDER))
                msg["To"] = email

                part = MIMEText(html_content, "html")
                msg.attach(part)

                server.sendmail(EMAIL_SENDER, email, msg.as_string())
                print(f"✓ Başarıyla gönderildi: {email}")
                time.sleep(1)

            except Exception as e:
                print(f"✗ Hata ({email}): {e}")

    print("Tüm gönderimler tamamlandı!")


# ==========================================
# 6. ANA DÖNGÜ
# ==========================================
def main():
    arxiv_data = fetch_arxiv_papers()
    hn_data = fetch_hacker_news_ai()
    all_data = arxiv_data + hn_data

    if not all_data:
        print("Hiçbir veri toplanamadı!")
        return

    raw_text = ""
    for idx, item in enumerate(all_data, 1):
        raw_text += f"[{idx}] Kaynak: {item['source']}\nBaşlık: {item['title']}\nTarih: {item['date']}\nLink: {item['link']}\nÖzet: {item['summary']}\n\n"

    newsletter_html = generate_digest_with_opencode(raw_text)
    recipients = get_subscribers()
    send_newsletter_to_all(newsletter_html, recipients)


if __name__ == "__main__":
    main()
