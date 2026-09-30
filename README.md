# AI & Teknoloji Radarı

A weekly, Turkish-language AI and technology newsletter that writes and sends itself. Every Monday a GitHub Actions job collects the past week's AI news from six kinds of sources, asks an LLM to pick the 10 to 12 most important items and lay them out as an HTML email, and mails that email to every active subscriber.

Everything lives in one script, [`main.py`](main.py).

## How it works

0. **Check settings.** Before anything is collected, `check_config` makes sure the required secrets are present (see [Secrets](#secrets)). If something is missing, each problem is printed as a GitHub Actions error and the run stops at once, before any source is fetched or the LLM is called. `dry_run` runs skip this check.
1. **Collect.** `main.py` pulls candidate items from six sources (below). Each item carries a source, title, date (converted to Turkish, e.g. `28 Eylül 2026`), link and short summary. A source that fails is logged and skipped, so one broken feed does not stop the run. Every HTTP request has a timeout; RSS and Atom feeds (arXiv, The Verge, Ars Technica) are fetched with a 15-second limit via `fetch_feed`.
2. **Write.** All items go to an LLM in a single prompt. The model chooses the week's most important developments, prioritising new model launches, then viral, safety or scandal stories, then research and open source, and returns a complete HTML newsletter (header, a two-sentence summary, one card per item).
3. **Check.** The HTML is validated before anything is sent (see [LLM step](#llm-step)). If the model fails three times, the run stops with an error and no email goes out.
4. **Send.** The newsletter is emailed to each active subscriber through Gmail, with a personal unsubscribe link added to the footer.

## Sources

| # | Source | What is fetched |
|---|--------|-----------------|
| 1 | arXiv | 8 newest papers in `cs.AI` or `cs.LG` (Atom API) |
| 2 | Hacker News | Up to 6 stories from the last 7 days matching AI, LLM, Grok, Claude or OpenAI with more than 50 points (Algolia API) |
| 3 | GitHub | Up to 6 most-starred Python repos created in the last 7 days with the `ai`, `llm` or `machine-learning` topic (search API, unauthenticated) |
| 4 | Company blogs | 3 latest posts each from OpenAI, Google DeepMind, Anthropic (via an RSSHub mirror) and Hugging Face |
| 5 | Reddit | Top posts of the week from r/ChatGPT, r/singularity and r/LocalLLaMA |
| 6 | Tech media | 4 latest posts each from The Verge (AI section) and Ars Technica |

**Reddit** blocks unauthenticated JSON requests from data-centre IPs such as GitHub Actions runners. If `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` are set, the script uses Reddit's app-only OAuth API and keeps posts with more than 300 upvotes. Otherwise it falls back to a single combined RSS request (`r/ChatGPT+singularity+LocalLLaMA/top/.rss`), keeps up to 5 posts per subreddit, and retries once after an HTTP 429.

## LLM step

The model is called through [OpenCode Go](https://opencode.ai), which exposes an OpenAI-compatible API at `https://opencode.ai/zen/go/v1`; the script uses the `openai` Python client against it. The model defaults to `deepseek-v4.1-flash` and can be changed with the `OPENCODE_MODEL` environment variable.

Safeguards in `generate_digest_with_opencode` and `validate_digest_html`:

- Markdown code fences (```` ```html ````) around the answer are stripped.
- The HTML must be at least 2,000 characters, contain `<html>…</html>` and `<body>…</body>` in order, and contain at least 5 `http(s)` links.
- Up to 3 attempts, waiting 10 s and then 20 s between them. After the third failure the script exits with status 1 and sends nothing.

## Email step

**Subscribers** are read by `get_subscribers`, in this order:

1. **Google Sheet** (when `GCP_SA_KEY` and `SPREADSHEET_ID` are set). The first sheet is read with a service account (read-only scope). The header row is skipped; column B is the email, column C the status and column D the unsubscribe token (column A is ignored). Rows are read newest first, only the newest row per email counts, and only rows with status `AKTIF` are included.
2. **`subscribers.txt`** in the working directory, one email per line (lines starting with `#` are ignored). Used only if the sheet is not configured or has no active subscribers.
3. **`EMAIL_RECEIVER`** as a single recipient, if neither of the above gives anyone.

If the sheet is configured but cannot be read, or has no `AKTIF` rows, the newsletter still goes to the fallback recipients (2 or 3), but a GitHub Actions error is printed and the run ends with status 1, so a broken sheet never goes unnoticed.

**Sending** uses Gmail SMTP over SSL (`smtp.gmail.com:465`), logging in as `EMAIL_SENDER` with `EMAIL_PASSWORD`. Each subscriber gets their own copy, built by `build_message`:

- **Subject** ends with the send date, e.g. `🚀 Haftalık Yapay Zekâ & Teknoloji Radarı • 28 Eylül 2026`, so Gmail shows each week as its own conversation instead of grouping them.
- **Body** is `multipart/alternative`: a plain-text version generated from the HTML by `html_to_text` (links written as `text (url)`), followed by the HTML version.
- **Unsubscribe**: a footer link and a `List-Unsubscribe` header, both pointing to `WEB_APP_URL?action=unsubscribe&email=…&token=…`. The unsubscribe web app itself is not in this repository. If `WEB_APP_URL` or the subscriber's token is missing, the footer link is `#` and the header is left out. The one-click `List-Unsubscribe-Post` header is not sent, because it only works if the web app accepts a POST request.
- **Logo**: the prompt asks the model for an inline CSS badge with an emoji instead of an external image, so there is nothing for mail clients to block.

If there are no recipients, or any single email fails to send, the run exits with status 1 so the failure shows up in GitHub Actions. The other subscribers still receive their copy.

## Schedule and manual runs

The workflow is [`.github/workflows/newsletter.yml`](.github/workflows/newsletter.yml).

- **Schedule:** every Monday at 06:00 UTC (09:00 Turkey time), cron `0 6 * * 1`.
- **Manual run:** Actions tab → *Haftalik Teknoloji ve AI Bulteni* → *Run workflow*. It has two inputs:
  - `dry_run` (default off): only collect data from the sources and print a summary, including the Reddit items. The LLM is not called and no email is sent.
  - `preview` (default off): generate the full newsletter, but email it only to the owner (`PREVIEW_EMAIL`, or `EMAIL_RECEIVER` if that is unset) with an `[ÖNİZLEME]` subject prefix. The subscriber list is never read. The HTML is also uploaded as the `newsletter-preview` run artifact.

> [!WARNING]
> A manual run with both `dry_run` and `preview` off sends the real newsletter to every active subscriber. Use `dry_run` to test the sources and `preview` to see the finished email.

## Web archive

Every issue that is actually sent to subscribers is also published to a public web archive on GitHub Pages: an index page listing all issues (newest first) and one page per issue at `issues/YYYY-MM-DD.html`. Preview and `dry_run` runs never publish.

How it works: after a real send, `main.py` saves the shared newsletter HTML to `issue.html`. The workflow's *Web Arşivine Ekle* step then runs [`archive.py`](archive.py) on a checkout of the `gh-pages` branch (created on the first run) and pushes the result. Before publishing, `archive.py` removes the subscriber footer, any link carrying an unsubscribe action, `token=` or `email=` parameter, `mailto:` links, scripts and inline event handlers, so no subscriber data reaches the web. Re-running on the same day replaces that day's page.

One-time setup, after the first real send has created the `gh-pages` branch: Settings → Pages → *Build and deployment* → Source: *Deploy from a branch* → Branch: `gh-pages`, folder `/ (root)` → Save. The site is then at `https://<user>.github.io/ai-weekly-news/`. GitHub Pages on a private repository needs a paid plan (GitHub Pro or higher), and the published site is public either way.

To build the archive locally: `python archive.py newsletter.html site` writes `site/index.html` and today's issue page.

## Secrets

Set these under *Settings → Secrets and variables → Actions*. The workflow passes them to `main.py` as environment variables of the same name.

At startup (except in `dry_run`) the run stops with a clear error if any "Yes" secret is missing, if only one of `GCP_SA_KEY` and `SPREADSHEET_ID` is set, if `GCP_SA_KEY` is not valid JSON, or if there is no recipient at all (the sheet, `subscribers.txt` or `EMAIL_RECEIVER`; for `preview` runs, `PREVIEW_EMAIL` or `EMAIL_RECEIVER`).

| Secret | Required | Used for |
|--------|----------|----------|
| `OPENCODE_API_KEY` | Yes | OpenCode Go API key for the LLM |
| `EMAIL_SENDER` | Yes | Gmail address the newsletter is sent from |
| `EMAIL_PASSWORD` | Yes | Gmail app password for `EMAIL_SENDER` |
| `GCP_SA_KEY` | For the Sheet | Google service account key, as the full JSON text |
| `SPREADSHEET_ID` | For the Sheet | ID of the subscriber Google Sheet (shared with the service account) |
| `WEB_APP_URL` | For unsubscribe links | Base URL of the unsubscribe web app |
| `EMAIL_RECEIVER` | No | Fallback single recipient when no other subscriber list is available |
| `PREVIEW_EMAIL` | No | Where `preview` runs send the newsletter (falls back to `EMAIL_RECEIVER`) |
| `REDDIT_CLIENT_ID` | No | Reddit app ID; enables the OAuth path |
| `REDDIT_CLIENT_SECRET` | No | Reddit app secret; enables the OAuth path |

`OPENCODE_MODEL` is optional and is not passed by the workflow today, so the default model is used there.

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

## Tests and CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every pull request and on pushes to `main`. It gets no secrets, never calls the LLM and never sends email. It runs:

1. `ruff check .` (rules in [`pyproject.toml`](pyproject.toml))
2. `python -m py_compile main.py` and `python -c "import main"`
3. `pytest -q`

The tests in [`tests/`](tests) use no network: they cover date parsing and HTML validation, the Reddit RSS fallback (with a fake `requests.get`), send-failure reporting (with a fake SMTP server), preview mode, the email format (subject, plain-text part and unsubscribe header), and the startup settings check, loud Sheets fallback and feed timeouts.

To run the same checks locally:

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
pytest -q
```
