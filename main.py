import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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

    # OpenCode Go OpenAI-uyumlu endpoint yapılandırması
    client = OpenAI(
        base_url="https://opencode.ai/zen/go/v1",
        api_key=OPENCODE_API_KEY,
        default_headers={"User-Agent": "newsletter-agent/1.0"}
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
2. Başlangıçta 2 cümlelik samimi ve vizyoner bir "Haftanın Özeti" girişi yap.
3. Seçilen her gelişme için temiz bir HTML kart tasarımı (`border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; margin-bottom: 20px; font-family: sans-serif;`) kullan.
4. Her kartta şunlar bulunsun:
   - **Başlık** (varsa ilgili model/teknoloji adı)
   - **Kategori Etiketi**: (Yeni Model, Araştırma/Makale, Açık Kaynak, Endüstri)
   - **Özet**: 2-3 cümle ile ne yapıldığını ve teknik yeniliği açıkla.
   - **Neden Önemli?**: Sektöre ve geleceğe etkisini 1-2 cümleyle açıkla.
   - **Kaynak Linki**: Doğrudan tıklanabilir bir buton veya link formatında kaynak URL'si.
5. Sadece geçerli `<html><body>...</body></html>` kodunu döndür, markdown tırnakları (```html) KULLANMA.
"""

    # OpenCode Go'da yer alan popüler modellerden birini seçebilirsiniz:
    # örn: "qwen3.5-plus", "deepseek-v4-pro" veya "kimi-k2.7-code"
    response = client.chat.completions.create(
        model="qwen3.5-plus",
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
    msg["From"] = EMAIL_SENDER
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
