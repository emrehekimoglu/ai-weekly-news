import time, datetime, requests
t=int(time.time())-7*86400
UA={"User-Agent":"ai-weekly-news/1.0 (+https://github.com/emrehekimoglu/ai-weekly-news)"}
def hn(url,h=None):
    try:
        r=requests.get(url,headers=h,timeout=10); j=r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        print("HN",r.status_code,j.get("nbHits"),len(j.get("hits",[])),url[:140], "" if r.ok else r.text[:200])
    except Exception as e: print("HN ERR",url[:100],e)
base="https://hn.algolia.com/api/v1/"
hn(base+f"search_by_date?query=AI%20OR%20LLM%20OR%20Grok%20OR%20Claude%20OR%20OpenAI&tags=story&numericFilters=points>50,created_at_i>{t}")
hn(base+f"search_by_date?query=AI%20OR%20LLM%20OR%20Grok%20OR%20Claude%20OR%20OpenAI&tags=story&numericFilters=points>50,created_at_i>{t}",UA)
for q in ["AI","LLM","OpenAI","Claude"]:
    hn(base+f"search_by_date?query={q}&tags=story&numericFilters=points>50,created_at_i>{t}&hitsPerPage=50",UA)
    hn(base+f"search?query={q}&tags=story&numericFilters=points>50,created_at_i>{t}&hitsPerPage=50",UA)
hn(base+f"search_by_date?tags=story&numericFilters=points>50,created_at_i>{t}",UA)
s=(datetime.date.today()-datetime.timedelta(7)).isoformat()
def gh(q,h):
    r=requests.get("https://api.github.com/search/repositories",params={"q":q,"sort":"stars","order":"desc"},headers=h,timeout=10)
    print("GH",r.status_code,r.json().get("total_count"),q,r.headers.get("x-ratelimit-remaining"),"" if r.ok else r.text[:300])
r=requests.get("https://api.github.com/search/repositories?q=(topic:ai+OR+topic:llm+OR+topic:machine-learning)"+f"+language:python+created:>{s}&sort=stars&order=desc",headers={"Accept":"application/vnd.github.v3+json","User-Agent":"newsletter-agent/1.0"},timeout=10)
print("GH OLD",r.status_code,r.json().get("total_count"),r.text[:300])
h={"User-Agent":"newsletter-agent/1.0","Accept":"application/vnd.github+json"}
gh(f"topic:llm language:python created:>{s}",h)
gh(f"topic:ai language:python created:>{s}",h)
gh(f"topic:llm created:>{s}",h)
gh(f"topic:llm OR topic:ai created:>{s}",h)
