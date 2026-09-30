import os
import uuid
import json
import time
import re
from datetime import datetime, timezone
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
WEB_APP_URL = os.environ.get("WEB_APP_URL", "")
MODEL_NAME = os.environ.get("OPENCODE_MODEL", "qwen3.8-max")


# ==========================================
# YARDIMCI: TARİHİ TÜRKÇEYE ÇEVİRME
# ==========================================
def format_to_turkish_date(date_str):
    """'2026-09-28' veya ISO tarihleri '28 Eylül 2026' formatına çevirir."""
    if not date_str:
        return "Bu Hafta"
    try:
        clean_str = date_str[:10]
        dt = datetime.strptime(clean_str, "%Y-%m-%d")
        months = [
            "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
            "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"
        ]
        return f"{dt.day} {months[dt.month - 1]} {dt.year}"
    except Exception:
        return date_str[:10]


# ==========================================
# 2. GERÇEK YAYIN TARİHLERİYLE VERİ TOPLAMA
# ==========================================
def fetch_arxiv_papers():
    """arXiv resmi Atom API üzerinden son makaleleri gerçek yayın tarihleriyle çeker."""
    print("arXiv makaleleri toplanıyor...")
    # Resmi Atom API hem yayınlanma tarihini kesin verir hem de tarihe göre sıralar
    url = "https://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=10"
    feed = feedparser.parse(url)
    items = []
    
    for entry in feed.entries:
        # arXiv Atom API'sinde yayın tarihi 'published' içindedir (Örn: 2026-09-28T14:20:00Z)
        raw_pub = entry.get("published", entry.get("updated", ""))
        tr_date = format_to_turkish_date(raw_pub)

        items.append({
            "source": "arXiv",
            "title": entry.title.replace("\n", " ").strip(),
            "date": tr_date,
            "link": entry.link,
            "summary": entry.summary[:400].replace("\n", " ").strip()
        })
    return items


def fetch_hacker_news_ai():
    """Hacker News üzerinden sadece son 7 günde çıkan haberleri gerçek tarihleriyle çeker."""
    print("Hacker News trendleri toplanıyor...")
    try:
        # Son 7 günün Unix zaman damgası filtresi
        seven_days_ago = int(time.time()) - (7 * 24 * 3600)
        url = f"https://hn.algolia.com/api/v1/search_by_date?query=AI%20OR%20LLM&tags=story&numericFilters=points>60,created_at_i>{seven_days_ago}"
        res = requests.get(url, timeout=10).json()
        
        items = []
        for hit in res.get("hits", [])[:8]:
            created_at = hit.get("created_at", "")
            tr_date = format_to_turkish_date(created_at)

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


# ==========================================
# 3. AKTİF ABONELERİ ÇEKME
# ==========================================
def get_subscribers():
    """Google Sheets üzerinden durumu 'AKTIF' olan kişileri çeker."""
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
            for row in rows[1:]:
                if len(row) >= 4:
                    email = row[1].strip()
                    status = row[2].strip().upper()
                    token = row[3].strip()
                    
                    if status == "AKTIF" and "@" in email:
                        active_subscribers.append({"email": email, "token": token})

            if active_subscribers:
                print(f"✓ Toplam {len(active_subscribers)} AKTİF abone bulundu.")
                return active_subscribers
            else:
                print("[UYARI] Tabloda 'AKTIF' statüsünde abone bulunamadı!")

        except Exception as e:
            print(f"[HATA] Google Sheets okunurken hata: {e}")

    # subscribers.txt kontrolü
    if os.path.exists("subscribers.txt"):
        emails = []
        with open("subscribers.txt", "r", encoding="utf-8") as f:
            for line in f:
                em = line.strip()
                if "@" in em and not em.startswith("#"):
                    emails.append({"email": em, "token": ""})
        if emails:
            return emails

    return [{"email": EMAIL_RECEIVER, "token": ""}] if EMAIL_RECEIVER else []


# ==========================================
# 4. BÜLTEN ÜRETİMİ (TARİH TALİMATLI PROMPT)
# ==========================================
def generate_digest_with_opencode(raw_data):
    """HTML bülten üretir."""
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
Aşağıda son bir haftada yayımlanan ham teknoloji ve araştırma içerikleri (orijinal yayımlanma/duyurulma tarihleriyle) yer alıyor:

{raw_data}

GÖREVİN:
Bu verileri filtreleyerek gerçekten çığır açıcı, sektörde ses getirebilecek veya yeni bir paradigma başlatan EN ÖNEMLİ 5-7 gelişmeyi seç.
Bunu bir e-posta bülteni olarak modern, temiz ve profesyonel bir HTML formatında yaz.

ŞABLON KURALLARI:
1. Türkçe yaz.
2. EN ÜSTE ŞIK BİR HEADER ALANI EKLE:
   - Yuvarlak yapay zekâ ikonu: `<img src="https://cdn-icons-png.flaticon.com/512/4712/4712109.png" width="44" height="44" style="vertical-align: middle; margin-right: 12px; border-radius: 50%;">`
   - Yanına kalın harflerle "AI & TEKNOLOJİ RADARI" başlığı.
   - Altına gri ve küçük puntolarla "Haftalık Kürasyon • Yeni Modeller, Makaleler ve Gelişmeler" notu.
   - Altına ince bir ayırıcı çizgi (`<hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">`).
3. Header'ın hemen altına 2 cümlelik samimi ve vizyoner bir "Haftanın Özeti" girişi yap.
4. Seçilen her gelişme için temiz bir HTML kart tasarımı (`border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px; margin-bottom: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #ffffff;`) kullan.
5. HER KARTTA ZORUNLU ALANLAR:
   - **Başlık**: Kalın ve belirgin (varsa ilgili model/teknoloji adı).
   - **Tarih & Kategori Rozetleri (ÇOK KRİTİK KURAL)**:
     Başlığın hemen altında yan yana iki rozet yer almalı:
     1. Tarih Rozeti: `<span style="background: #f1f5f9; padding: 3px 8px; border-radius: 4px; font-size: 12px; color: #475569; margin-right: 8px;">📅 [Yayın Tarihi]</span>`
        **ÖNEMLİ:** Buraya ASLA bugünün tarihini veya bültenin gönderildiği tarihi yazma! Yukarıda sana verilen ham verideki "Yayın Tarihi:" alanında ne yazıyorsa (Örn: 28 Eylül 2026, 26 Eylül 2026) BİREBİR o tarihi yaz.
     2. Kategori Rozeti: `<span style="background: #e0f2fe; padding: 3px 8px; border-radius: 4px; font-size: 12px; color: #0369a1;">[Kategori: Yeni Model / Makale / Endüstri / Açık Kaynak]</span>`
   - **Özet**: 2-3 cümle ile ne yapıldığını ve teknik yeniliği açıkla.
   - **Neden Önemli?**: Sektöre ve geleceğe etkisini 1-2 cümleyle açıkla.
   - **Kaynak Butonu**: Doğrudan tıklanabilir kaynak linki (`<a href="..." style="display: inline-block; margin-top: 10px; color: #2563eb; text-decoration: none; font-weight: bold; font-size: 13px;">Kaynağa Git →</a>`).
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
# 5. KİŞİYE ÖZEL E-POSTA DAĞITIMI
# ==========================================
def send_newsletter_to_all(html_content, recipients):
    """Bülteni her aboneye kendi kişiselleştirilmiş iptal linkiyle gönderir."""
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
        raw_text += f"[{idx}] Kaynak: {item['source']}\nBaşlık: {item['title']}\nYayın Tarihi: {item['date']}\nLink: {item['link']}\nÖzet: {item['summary']}\n\n"

    newsletter_html = generate_digest_with_opencode(raw_text)
    recipients = get_subscribers()
    send_newsletter_to_all(newsletter_html, recipients)


if __name__ == "__main__":
    main()
