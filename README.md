# AI & Teknoloji Radarı

A weekly, Turkish-language AI and technology newsletter that writes and sends itself. Every Monday a GitHub Actions job collects the past week's AI news from six kinds of sources, asks an LLM to pick the 10 to 12 most important items and summarise them in Turkish, fills those into a fixed email template, and mails that email to every active subscriber.

`main.py` is only the entry point the workflow runs; the code lives in the [`newsletter/`](newsletter) package:

| Module | Job |
|--------|-----|
| `config.py` | Settings read from environment variables, and the startup check |
| `models.py` | `NewsItem`, the shared shape of a collected story (source, title, date, link, summary) |
| `sources/` | One module per source, plus `SOURCES`, the list the run walks through |
| `llm.py` | Prompt, LLM call with retries, and checking the model's JSON answer |
| `render.py` and `templates/` | The email design: Jinja2 templates for the HTML and plain-text versions |
| `subscribers.py` | Reading the subscriber sheet and fallbacks, and the preview recipient |
| `mailer.py` | Subject, plain-text part, unsubscribe footer and header, and sending over Gmail |
| `dedup.py` | Spotting the same story from two sources (by normalised link or title) |
| `history.py` | Remembering which stories earlier issues sent, in [`data/history.json`](data/history.json) |
| `app.py` | The run itself: check, collect, filter, write, send |
| `report.py` | Story counts per source and warnings, saved to `run_report.json` for the alert |
| `alert.py` | The failure alert email (run by the workflow's last step) |

To add a source, write a module in `newsletter/sources/` with a `fetch()` function that returns a list of `NewsItem`, and add it to `SOURCES` in [`newsletter/sources/__init__.py`](newsletter/sources/__init__.py).

Output goes through Python's `logging` module to standard output, one plain line per message, so lines starting with `::error::` still show up as errors in GitHub Actions.

## How it works

0. **Check settings.** Before anything is collected, `config.check_config` makes sure the required secrets are present (see [Secrets](#secrets)). If something is missing, each problem is printed as a GitHub Actions error and the run stops at once, before any source is fetched or the LLM is called. `dry_run` runs skip this check.
1. **Collect.** The run walks through the seven sources in `SOURCES` (below). Each item is a `NewsItem` carrying a source, title, date (converted to Turkish, e.g. `28 Eylül 2026`), link and short summary. A source that raises an error is logged and skipped, so one broken feed does not stop the run. Every HTTP request has a timeout; RSS and Atom feeds (arXiv, The Verge, Ars Technica) are fetched with a 15-second limit via `sources/feeds.py`.
2. **Filter.** Repeats are removed before the LLM sees anything (see [Repeated stories](#repeated-stories)): the same story from two sources is kept once, and stories already sent in the last 8 issues are dropped.
3. **Write.** The remaining items go to an LLM in a single prompt. The model chooses the week's most important developments, prioritising new model launches, then viral, safety or scandal stories, then research and open source, and answers in JSON: a headline for the week (also used as the email subject), a two-sentence intro, three one-line "30 saniyede bu hafta" takeaways, an optional "Haftanın Rakamı" number with a one-sentence explanation, plus, for each pick, the item's number, a Turkish title, a category and a 2 to 3 sentence summary. The email is laid out like a magazine: the headline, the takeaways, the top pick as the cover story, the number, then the remaining picks ranked 02 onwards. An optional "Türkiye'den" section adds up to 3 stories about Turkish companies, startups or research from the Turkish sources; if there are none that week the model returns an empty list and the section is left out.
4. **Check and render.** The JSON is validated (see [LLM step](#llm-step)); if the model fails three times, the run stops with an error and no email goes out. The picks are then rendered with the templates in [`newsletter/templates/`](newsletter/templates), so the layout is the same every week.
5. **Send.** The newsletter is emailed to each active subscriber through Gmail, with a personal unsubscribe link in the footer.
6. **Remember.** After a real send that reached at least one subscriber, the issue's stories are added to `data/history.json` and the workflow commits that file.

## Sources

| # | Source | What is fetched |
|---|--------|-----------------|
| 1 | arXiv | 8 newest papers in `cs.AI` or `cs.LG` (Atom API) |
| 2 | Hacker News | Up to 6 stories from the last 7 days matching AI, LLM, Grok, Claude or OpenAI with more than 50 points (Algolia API) |
| 3 | GitHub | Up to 6 most-starred Python repos created in the last 7 days with the `ai`, `llm` or `machine-learning` topic (search API, unauthenticated) |
| 4 | Company blogs | 3 latest posts each from OpenAI, Google DeepMind, Anthropic (via an RSSHub mirror) and Hugging Face |
| 5 | Reddit | Top posts of the week from r/ChatGPT, r/singularity and r/LocalLLaMA |
| 6 | Tech media | 4 latest posts each from The Verge (AI section) and Ars Technica |
| 7 | Turkish tech media | Up to 5 posts from the last 8 days each from Webrazzi (AI section), Egirişim and Webtekno; the general feeds keep only AI, startup and investment stories. These are the only candidates for the "Türkiye'den" section |

After collecting, the run logs one line with how many stories each source returned (`Kaynak özeti: arXiv 8, Hacker News 6, …`). A source that returns nothing gets a yellow `::warning::` in the Actions log and is listed in the [alert email](#failure-alert).

**Reddit** blocks unauthenticated JSON requests from data-centre IPs such as GitHub Actions runners. If `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` are set, the script uses Reddit's app-only OAuth API and keeps posts with more than 300 upvotes. Otherwise it falls back to a single combined RSS request (`r/ChatGPT+singularity+LocalLLaMA/top/.rss`), keeps up to 5 posts per subreddit, and retries once after an HTTP 429.

## Repeated stories

**Across sources in the same week** (`dedup.remove_duplicates`): items are compared by link after dropping `http(s)`, `www.`, tracking parameters such as `utm_*` and `ref`, the `#fragment` and a trailing `/`, and by title after lower-casing and removing punctuation. The first one in source order is kept (arXiv, Hacker News, GitHub, company blogs, Reddit, tech media, Turkish tech media). Stories that are the same news under different links and titles are left to the LLM, which is told to pick only the best source for each event.

**Across weeks** (`history.py`): [`data/history.json`](data/history.json) lists the title, link and source of every story in the last 8 issues. On each run, collected items whose link was already sent are dropped, and the titles from the last 2 issues are listed in the prompt so the model does not pick the same event again from a new link (unless there is real news, such as an announced model being released). The file is updated only after a real send reaches at least one subscriber; `preview` and `dry_run` never change it. The *Sayı Geçmişini Kaydet* workflow step commits it back to the repository, which is why the job has `contents: write` permission. If `main` is ever protected against direct pushes, that step will fail and the history will stop updating.

To let a story through again, delete its entry from `data/history.json`.

If every collected item has already been sent, the run exits with status 1 and sends nothing.

## LLM step

The model is called through [OpenCode Go](https://opencode.ai), which exposes an OpenAI-compatible API at `https://opencode.ai/zen/go/v1`; the script uses the `openai` Python client against it. The model defaults to `deepseek-v4.1-flash` and can be changed with the `OPENCODE_MODEL` environment variable.

The model only chooses and writes; it never writes HTML or links. Each pick refers to an item by its number in the prompt, and the link and date always come from that collected item, so a made-up URL cannot reach subscribers.

Safeguards in `llm.generate_digest` and `llm.parse_digest`:

- The JSON object is taken from the answer even if the model wraps it in ```` ```json ```` fences or extra text.
- The intro and each pick's title and summary must be non-empty text, and each number must match a collected item. Repeated numbers are dropped, an unknown category becomes `Endüstri`, and at most 12 picks are kept. The headline, takeaways and number are optional: if any is missing or malformed it is logged and that block is left out of the email, and the subject falls back to the dated default.
- At least 5 valid picks are required.
- Each answer may take up to 10 minutes (`LLM_TIMEOUT_SECONDS`; `qwen3.8-max` takes about 5 minutes for one issue). The `openai` client's own silent retries are off, so a slow answer is never requested twice in parallel and billed twice.
- Up to 3 attempts, waiting 10 s and then 20 s between them. If all three fail, the same 3 attempts are made with a backup model (`qwen3.8-max` by default, changed with `OPENCODE_FALLBACK_MODEL`; set it empty or equal to the main model to turn the backup off). An issue written by the backup model goes out as usual and the [alert email](#failure-alert) says so. If the backup fails too, the script exits with status 1 and sends nothing.

## Email step

**Subscribers** are read by `subscribers.get_subscribers`, in this order:

1. **Google Sheet** (when `GCP_SA_KEY` and `SPREADSHEET_ID` are set). The first sheet is read with a service account (read-only scope; the weekly stats below use a separate write). The header row is skipped; column B is the email, column C the status and column D the unsubscribe token (column A is ignored). Rows are read newest first, only the newest row per email counts, and only rows with status `AKTIF` are included.
2. **`subscribers.txt`** in the working directory, one email per line (lines starting with `#` are ignored). Used only if the sheet is not configured or has no active subscribers.
3. **`EMAIL_RECEIVER`** as a single recipient, if neither of the above gives anyone.

If the sheet is configured but cannot be read, or has no `AKTIF` rows, the newsletter still goes to the fallback recipients (2 or 3), but a GitHub Actions error is printed and the run ends with status 1, so a broken sheet never goes unnoticed.

**Sending** uses Gmail SMTP over SSL (`smtp.gmail.com:465`), logging in as `EMAIL_SENDER` with `EMAIL_PASSWORD`. Each subscriber gets their own copy, built by `mailer.build_message`:

- **Subject** ends with the send date, e.g. `🚀 Haftalık Yapay Zekâ & Teknoloji Radarı • 28 Eylül 2026`, so Gmail shows each week as its own conversation instead of grouping them.
- **Body** is `multipart/alternative`: a plain-text version from `newsletter.txt.j2`, followed by the HTML version from `newsletter.html.j2`. Both are rendered per subscriber so the unsubscribe link is theirs. Text from the model is HTML-escaped.
- **Unsubscribe**: a footer link and a `List-Unsubscribe` header, both pointing to `WEB_APP_URL?action=unsubscribe&email=…&token=…`. The page behind it is the Cloudflare Worker in [`worker/`](worker) (see [Link pages](#link-pages-cloudflare-worker)). If `WEB_APP_URL` or the subscriber's token is missing, the footer link is `#` and the header is left out. The one-click `List-Unsubscribe-Post` header is not sent, because it only works if the web app accepts a POST request.
- **Feedback**: each story has small 👍 👎 links, and a *Bu sayı nasıldı?* box above the footer rates the whole issue (the plain-text part has only the issue vote). See [Feedback links](#feedback-links).
- **Sharing**: the footer links to the issue's web archive page (`https://<owner>.github.io/<repo>/issues/YYYY-MM-DD.html`, derived from `GITHUB_REPOSITORY`; override with an `ARCHIVE_URL` env value). Each archive page ends with X, LinkedIn, WhatsApp, Telegram and email share links that carry only that public page address.
- **Logo**: the template uses an inline CSS badge with an emoji instead of an external image, so there is nothing for mail clients to block.

To change the design, edit [`newsletter/templates/newsletter.html.j2`](newsletter/templates/newsletter.html.j2) (and the `.txt.j2` twin), then check it with a `preview` run.

If there are no recipients, or any single email fails to send, the run exits with status 1 so the failure shows up in GitHub Actions. The other subscribers still receive their copy.

## Subscriber stats

After every real send, `newsletter/stats.py` appends one row to a **Stats** tab in the same Google Sheet (the tab is created on the first run). Each row holds only counts, never an email address:

| Tarih | Aktif abone | Yeni kayıt | Ayrılan | Net değişim | Gönderilen | Başarısız | Kayıtlı e-posta | Pasif |
|---|---|---|---|---|---|---|---|---|

- **Aktif abone**: unique emails whose newest row is `AKTIF`. **Kayıtlı e-posta**: unique emails that appear in the sheet at all. **Pasif**: the rest.
- **Yeni kayıt** is the growth of *Kayıtlı e-posta* since the previous row, **Ayrılan** the growth of *Pasif* (never below 0, so a re-subscription does not count as a negative), and **Net değişim** the change in *Aktif abone*. They are left empty on the first row. A person who unsubscribes and another who re-subscribes in the same week cancel out in *Ayrılan*.
- The run log prints the same counts in one line. Preview and `dry_run` runs never write stats, and neither does a send that fell back to `subscribers.txt` or `EMAIL_RECEIVER`.
- Writing needs the service account to be an **Editor** on the sheet (Share → the service account's `client_email` → Editor). Without it the run prints a GitHub Actions warning and carries on; the newsletter itself is not affected.

## Feedback links

The 👍/👎 links point to `WEB_APP_URL?action=vote&issue=YYYY-MM-DD&story=N&v=up|down&voter=…`, handled by the same Worker as unsubscribe. `story=0` is the whole issue; `1`, `2`, … is the story's position in the email, which matches the order of that issue's `entries` in [`data/history.json`](data/history.json). Links never carry the subscriber's email or token: `voter` is the first 12 hex characters of `sha256("<issue>:<token>")`, so a reader can change their vote but can't be followed across issues or traced back to an address. Subscribers without a token (fallback recipients) vote anonymously. Preview emails use `issue=onizleme-YYYY-MM-DD` so test clicks stay separate. The links are left out of the web archive and of the saved preview HTML.

Opening a vote or unsubscribe link with GET changes nothing: the Worker returns a tiny page that re-sends the same link as a POST with JavaScript (or a button if JavaScript is off). People see no difference, but link scanners that open every link in an email (mail-tester, Outlook Safe Links, corporate filters) don't run JavaScript, so they can't cast votes or unsubscribe anyone. Gmail's one-click unsubscribe button POSTs directly.

Votes land in a *Geri Bildirim* sheet of the subscriber spreadsheet (created on the first vote) with the columns time (UTC), issue, story, vote and voter. "Türkiye'den" stories are numbered after the main stories, as in `history.json`. The vote is saved as soon as the link is opened. A mail scanner that opens every link could cast a vote; because each reader's later vote on the same story replaces the earlier one, a real click after that still counts.

## Link pages (Cloudflare Worker)

Every link a reader clicks (signing up, confirming a signup, unsubscribing, voting) opens [`worker/src/index.js`](worker/src/index.js), a Cloudflare Worker. It replaced an Apps Script web app, which showed Google Drive's "Maalesef şu anda dosyayı açamıyoruz" page to anyone signed in to more than one Google account. The Worker reads and writes the subscriber sheet through the Google Sheets API with the same service account as the newsletter (`GCP_SA_KEY`), so readers never touch Google sign-in. It accepts the same addresses the old web app did:

- `?action=confirm&email=…&token=…` sets column C of the matching row to `AKTIF`.
- `?action=unsubscribe&email=…&token=…` sets it to `IPTAL`.
- `?action=vote&…` records a vote, as described above.

### Signup page

The Worker also serves the newsletter's own signup page at `/abone` (and at the bare Worker address). A reader types their email and presses *Abone Ol*; the Worker then:

1. Checks the address and the first sheet. If the address's newest row is `AKTIF` it says "Zaten abonesiniz" and sends nothing. If a confirmation email went to the same address in the last 10 minutes, it doesn't send another.
2. Sends a confirmation email from `EMAIL_SENDER` through Gmail SMTP (`smtp.gmail.com:465`, with the same app password as the newsletter), using [`worker/src/smtp.js`](worker/src/smtp.js).
3. Appends a row `time (UTC) | email | BEKLIYOR | token` to the first sheet. The confirm link in the email sets it to `AKTIF`, exactly like a Google Form signup.

To protect the Gmail account's daily sending limit (which the Monday issue also uses), the page sends at most 50 confirmation emails per 24 hours, counted from the rows it wrote. A hidden field catches simple bots. Nothing goes through Google sign-in.

The Google Form keeps working alongside it: its Apps Script `onFormSubmit` trigger still writes the token and sends its own confirmation email, with `WEB_APP_URL` pointing at the Worker.

The Worker is deployed by [`.github/workflows/worker.yml`](.github/workflows/worker.yml) on every push to `main` that changes `worker/`, or by hand from the Actions tab. It passes `GCP_SA_KEY`, `SPREADSHEET_ID`, `EMAIL_SENDER` and `EMAIL_PASSWORD` to the Worker as secrets; the archive address for the signup page is `ARCHIVE_URL` in [`worker/wrangler.toml`](worker/wrangler.toml). Without the Cloudflare secrets the workflow only runs the tests and prints a warning. Tests: `cd worker && node --test` (no network; Google is faked).

One-time setup:

1. Create a free Cloudflare account, open *Workers & Pages* once so it picks your `workers.dev` subdomain, and note the *Account ID* shown there.
2. Create an API token (*My Profile → API Tokens → Create Token → Edit Cloudflare Workers* template) and add it as the `CLOUDFLARE_API_TOKEN` secret, with the account ID as `CLOUDFLARE_ACCOUNT_ID`.
3. Share the subscriber sheet with the service account's `client_email` as **Editor** (the newsletter itself still only reads).
4. Run *Worker'ı Yayınla* from the Actions tab. The Worker is at `https://ai-radar.<subdomain>.workers.dev/`.
5. Set the `WEB_APP_URL` secret to that address, and set `WEB_APP_URL` in the Apps Script `Code.js` to it as well, so confirmation emails use it.
6. Set the `SIGNUP_URL` secret to `https://ai-radar.<subdomain>.workers.dev/abone`, so the email and the web archive link to the signup page.


## Schedule and manual runs

The workflow is [`.github/workflows/newsletter.yml`](.github/workflows/newsletter.yml).

- **Schedule:** every Monday at 03:00 UTC (06:00 Turkey time), cron `0 3 * * 1`, with a backup run at 04:37 UTC in case GitHub drops the first one. Issues sent by a scheduled run are marked `"scheduled": true` in `data/history.json`. The backup exits without doing anything if a scheduled run already sent an issue in the last 6 days. Manual sends don't count, so a manual issue on Sunday doesn't stop Monday's issue.
- **Manual run:** Actions tab → *Haftalik Teknoloji ve AI Bulteni* → *Run workflow*. It has these inputs:
  - `dry_run` (default off): only collect data from the sources and print how many items each source returned, with every item's title, and how many are left after removing repeats. The LLM is not called and no email is sent.
  - `preview` (default off): generate the full newsletter, but email it only to the owner (`PREVIEW_EMAIL`, or `EMAIL_RECEIVER` if that is unset) with an `[ÖNİZLEME]` subject prefix. The subscriber list is never read. The HTML is also uploaded as the `newsletter-preview` run artifact.
  - `fallback_test` (default off): a `preview` run with the main model deliberately set to a name that doesn't exist, so the backup model has to write the issue. If the preview email (subject starts with `[YEDEK MODEL TESTİ]`) arrives, the backup model works. If the run fails, the log says why.
  - `alert_test` (default off): send only a sample [failure alert](#failure-alert); nothing else runs.
  - `preview_to` (optional, only with `preview`): send this one preview to another address instead, for example a [mail-tester.com](https://www.mail-tester.com) test address to check the spam score.

> [!WARNING]
> A manual run with both `dry_run` and `preview` off sends the real newsletter to every active subscriber. Use `dry_run` to test the sources and `preview` to see the finished email.

### Failure alert

GitHub does not reliably email anyone when a scheduled run fails, so the workflow's last step, *Sorun Varsa Bana Haber Ver*, runs `python -m newsletter.alert` after every real send (never for `preview` or `dry_run`):

- If any step failed (no subscribers reached, model failed, a send failed, nothing collected, a crash), it emails the owner with a link to the run log, the story count per source, and the last 40 lines of the log. When the failed run is the 03:00 UTC one, the email says the 04:37 UTC backup run will try again.
- If the run succeeded but a source returned nothing, or the backup model wrote the issue, it sends a shorter "sent, with warnings" email.
- Otherwise it sends nothing.

To check that alerts arrive, run the workflow by hand with only `alert_test` ticked: it skips the newsletter entirely and sends one sample alert marked `[DENEME]`.

The alert goes to `ALERT_EMAIL` if set, else `PREVIEW_EMAIL`, else `EMAIL_SENDER` itself, using the same Gmail login as the newsletter. The newsletter step's output is copied to `run.log` for this. If the Gmail secrets themselves are missing, no alert can be sent; the run is still red in the Actions tab.

### Deliverability

The newsletter is sent through Gmail's own servers from a gmail.com address, so SPF, DKIM and DMARC already pass with Google's records; there is nothing to set up for them. What the code adds: `Date` and `Message-ID` headers, and RFC 8058 one-click unsubscribe (`List-Unsubscribe` plus `List-Unsubscribe-Post`), which Gmail and Yahoo expect from newsletters and show as an "Unsubscribe" button next to the sender. The Worker accepts that button's `POST` on the same unsubscribe link. The confirmation email and the "subscription confirmed" page ask readers to add the sender to their contacts, which is the strongest signal for keeping mail out of Spam.

## Web archive

Every issue that is actually sent to subscribers is also published to a public web archive on GitHub Pages: an index page listing all issues (newest first) and one page per issue at `issues/YYYY-MM-DD.html`. Preview and `dry_run` runs never publish.

How it works: after a real send, `newsletter/app.py` saves the shared newsletter HTML (rendered without any personal unsubscribe link) to `issue.html`. The workflow's *Web Arşivine Ekle* step then runs [`archive.py`](archive.py) on a checkout of the `gh-pages` branch (created on the first run) and pushes the result. Before publishing, `archive.py` removes the subscriber footer, any link carrying an unsubscribe action, `token=` or `email=` parameter, `mailto:` links, scripts and inline event handlers, so no subscriber data reaches the web. Re-running on the same day replaces that day's page.

One-time setup, after the first real send has created the `gh-pages` branch: Settings → Pages → *Build and deployment* → Source: *Deploy from a branch* → Branch: `gh-pages`, folder `/ (root)` → Save. The site is then at `https://<user>.github.io/ai-weekly-news/`. GitHub Pages on a private repository needs a paid plan (GitHub Pro or higher), and the published site is public either way.

To build the archive locally: `python archive.py newsletter.html site` writes `site/index.html` and today's issue page.

## Secrets

Set these under *Settings → Secrets and variables → Actions*. The workflow passes them to `main.py` as environment variables of the same name, and `newsletter/config.py` reads them.

At startup (except in `dry_run`) the run stops with a clear error if any "Yes" secret is missing, if only one of `GCP_SA_KEY` and `SPREADSHEET_ID` is set, if `GCP_SA_KEY` is not valid JSON, or if there is no recipient at all (the sheet, `subscribers.txt` or `EMAIL_RECEIVER`; for `preview` runs, `PREVIEW_EMAIL` or `EMAIL_RECEIVER`).

| Secret | Required | Used for |
|--------|----------|----------|
| `OPENCODE_API_KEY` | Yes | OpenCode Go API key for the LLM |
| `EMAIL_SENDER` | Yes | Gmail address the newsletter is sent from |
| `EMAIL_PASSWORD` | Yes | Gmail app password for `EMAIL_SENDER` |
| `GCP_SA_KEY` | For the Sheet | Google service account key, as the full JSON text |
| `SPREADSHEET_ID` | For the Sheet | ID of the subscriber Google Sheet (shared with the service account) |
| `WEB_APP_URL` | For unsubscribe and vote links | Address of the Cloudflare Worker (see [Link pages](#link-pages-cloudflare-worker)) |
| `CLOUDFLARE_API_TOKEN` | For the Worker | Cloudflare API token that can edit Workers |
| `CLOUDFLARE_ACCOUNT_ID` | For the Worker | Cloudflare account ID |
| `EMAIL_RECEIVER` | No | Fallback single recipient when no other subscriber list is available |
| `SIGNUP_URL` | No | Signup page link (the Worker's `/abone` page, or the Google Form). Adds a "forward to a friend / subscribe" box to the email and a subscribe link to the web archive; hidden when unset |
| `PREVIEW_EMAIL` | No | Where `preview` runs send the newsletter (falls back to `EMAIL_RECEIVER`) |
| `ALERT_EMAIL` | No | Where the [failure alert](#failure-alert) goes (falls back to `PREVIEW_EMAIL`, then `EMAIL_SENDER`) |
| `REDDIT_CLIENT_ID` | No | Reddit app ID; enables the OAuth path |
| `REDDIT_CLIENT_SECRET` | No | Reddit app secret; enables the OAuth path |

`OPENCODE_MODEL` and `OPENCODE_FALLBACK_MODEL` are optional and are not passed by the workflow today, so the default models are used there.

## Running locally

Requires Python 3.11. Dependency versions are pinned in `requirements.txt` and `requirements-dev.txt`; bump them there deliberately.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

To see what the sources return without calling the model or sending email (no secrets needed):

```bash
DRY_RUN=true python main.py
```

A full local run needs at least `OPENCODE_API_KEY`, `EMAIL_SENDER`, `EMAIL_PASSWORD` and a recipient. The simplest way to avoid mailing real subscribers is to leave `GCP_SA_KEY` and `SPREADSHEET_ID` unset and send only to yourself:

```bash
export OPENCODE_API_KEY=...
export EMAIL_SENDER=you@gmail.com
export EMAIL_PASSWORD=...        # Gmail app password
export EMAIL_RECEIVER=you@gmail.com
python main.py
```

(A `subscribers.txt` file in the repo root, if present, takes priority over `EMAIL_RECEIVER`.)

A successful local send also adds the issue to `data/history.json`. Don't commit that change unless you mean it, or the same stories will be skipped next Monday.

## Tests and CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every pull request and on pushes to `main`. It gets no secrets, never calls the LLM and never sends email. It runs:

1. `ruff check .` (rules in [`pyproject.toml`](pyproject.toml))
2. `python -m py_compile main.py` and `python -c "import main"`
3. `pytest -q`

The tests in [`tests/`](tests) use no network: they cover date parsing, the prompt and checking the model's JSON, the email templates, removing repeated stories and the issue history, skipping a failing source, dry-run output, the Reddit RSS fallback (with a fake `requests.get`), send-failure reporting (with a fake SMTP server), preview mode, the email format (subject, HTML escaping, plain-text part and unsubscribe header), the startup settings check, loud Sheets fallback and feed timeouts, and the subscriber stats (with a fake sheet).

To run the same checks locally:

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
pytest -q
```
