import os
import uuid
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
import feedparser
from openai import OpenAI
import requests

# 1. Ortam Değişkenleri
OPENCODE_API_KEY = os.environ.get("OPENCODE_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")


def fetch_arxiv_papers():
    """arXiv cs.AI ve cs.LG son makalelerini çeker."""
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
    """Hacker News üzerinde popüler AI başlıklarını çeker."""
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


def generate_digest_with_opencode(raw_data):
    """OpenCode Go API'sini kullanarak HTML bülteni üretir."""
    print("OpenCode Go üzerinden model bülteni hazırlıyor...")

    # OpenCode Go'nun zorunlu kıldığı session ID formatı (ses_ + 32 karakter hex)
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
     - Altına küçük ve gri fontla "Haftalık Kürasyon • Yeni Modeller, Makaleler ve Gelişmeler" notunu ve güncel tarihi düş.
     - Altına ince bir ayırıcı çizgi (`<hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">`) çek.
3. Header'ın hemen altına 2 cümlelik samimi ve vizyoner bir "Haftanın Özeti" girişi yap.
4. Seçilen her gelişme için temiz bir HTML kart tasarımı (`border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px; margin-bottom: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #ffffff;`) kullan.
5. Her kartta şunlar bulunsun:
   - **Başlık**: Kalın ve belirgin (varsa ilgili model/teknoloji adı)
   - **Kategori Etiketi**: Şık bir rozet (badge) gibi görünen renkli etiket (Örn: Yeni Model, Araştırma/Makale, Açık Kaynak, Endüstri)
   - **Özet**: 2-3 cümle ile ne yapıldığını ve teknik yeniliği açıkla.
   - **Neden Önemli?**: Sektöre ve geleceğe etkisini 1-2 cümleyle açıkla.
   - **Kaynak Linki**: Doğrudan tıklanabilir bir buton veya link formatında kaynak URL'si (`<a href="..." style="...">Kaynağa Git →</a>`).
6. Sadece geçerli `<html><body style="background-color: #f8fafc; padding: 20px; font-family: sans-serif;">...</body></html>` kodunu döndür, markdown tırnakları (```html) KULLANMA.
"""

    # OpenCode Go'da yer alan popüler modellerden birini seçebilirsiniz:
    # örn: "qwen3.5-plus", "deepseek-v4-pro" veya "kimi-k2.7-code"
    response = client.chat.completions.create(
        model="qwen3.8-max",
        temperature=0.3,
        messages=[
            {"role": "system", "content": "Sen profesyonel bir teknoloji bülteni editörüsün."},
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0].message.content


def send_email(html_content):
    """Oluşturulan HTML bültenini Gmail üzerinden postalar."""
    print("E-posta gönderiliyor...")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "🚀 Haftalık Yapay Zekâ & Teknoloji Radarı"
    
    # ESKİ: msg["From"] = EMAIL_SENDER
    # YENİ: Görünecek bülten adı ve e-posta adresi:
    msg["From"] = formataddr(("🤖 AI & Teknoloji Radarı", EMAIL_SENDER))
    
    msg["To"] = EMAIL_RECEIVER

    part = MIMEText(html_content, "html")
    msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
    print("E-posta başarıyla gönderildi!")

def main():
    arxiv_data = fetch_arxiv_papers()
    hn_data = fetch_hacker_news_ai()
    all_data = arxiv_data + hn_data

    if not all_data:
        print("Hiç veri toplanamadı!")
        return

    raw_text = ""
    for idx, item in enumerate(all_data, 1):
        raw_text += f"[{idx}] Kaynak: {item['source']}\nBaşlık: {item['title']}\nLink: {item['link']}\nÖzet: {item['summary']}\n\n"

    newsletter_html = generate_digest_with_opencode(raw_text)
    send_email(newsletter_html)


if __name__ == "__main__":
    main()
