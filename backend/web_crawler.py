"""
Full-site stealth crawler — Pinecone backend
BFS queue, lazy-load scroll, XHR interception, stealth, UA rotation
"""

import asyncio
import re
import json
import sys
import random
import hashlib
from collections import deque
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import stealth_async

from ingestion import chunk_text, embedder, pine_index, make_chunk_id
from config import CHUNK_SIZE, CHUNK_OVERLAP, DOCS_NAMESPACE

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

MAX_PAGES       = 200
REQUEST_TIMEOUT = 60000
SCROLL_STEPS    = 40
SCROLL_PAUSE    = 0.6
API_WAIT        = 4.0
MIN_DELAY       = 1.5
MAX_DELAY       = 3.5

SKIP_PATTERNS = re.compile(
    r"\.(pdf|docx?|xlsx?|pptx?|zip|rar|jpg|jpeg|png|gif|svg|ico|mp4|mp3|woff|css|js)$"
    r"|/login|/logout|/register|/cart|/checkout"
    r"|mailto:|tel:|javascript:|#",
    re.I
)

CAPTCHA_SIGNALS = [
    "captcha", "recaptcha", "hcaptcha", "cf-challenge",
    "challenge-running", "please verify", "are you human",
    "robot check", "cloudflare", "ddos-guard",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
]


def rnd(a=MIN_DELAY, b=MAX_DELAY):
    return random.uniform(a, b)

def get_ua():   return random.choice(USER_AGENTS)
def get_vp():   return random.choice(VIEWPORTS)

def should_skip(url: str) -> bool:
    return bool(SKIP_PATTERNS.search(url))

def detect_captcha(html: str) -> bool:
    low = html.lower()
    return any(s in low for s in CAPTCHA_SIGNALS)

def normalise_url(href: str, base: str) -> str | None:
    try:
        full   = urljoin(base, href.strip())
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            return None
        return parsed._replace(fragment="").geturl().rstrip("/")
    except Exception:
        return None


async def human_scroll(page):
    try:
        prev_height = 0
        stall = 0
        for _ in range(SCROLL_STEPS):
            await page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.75))")
            await asyncio.sleep(SCROLL_PAUSE)
            new_h  = await page.evaluate("document.body.scrollHeight")
            scroll = await page.evaluate("window.scrollY + window.innerHeight")
            if new_h == prev_height:
                stall += 1
                if stall >= 3 and scroll >= new_h:
                    break
            else:
                stall = 0
            prev_height = new_h
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.4)
    except Exception as e:
        print(f"[crawler] scroll error: {e}")


async def human_mouse(page):
    try:
        vp = page.viewport_size or {"width": 1366, "height": 768}
        for _ in range(random.randint(2, 4)):
            await page.mouse.move(
                random.randint(80, vp["width"] - 80),
                random.randint(80, vp["height"] - 80),
            )
            await asyncio.sleep(random.uniform(0.06, 0.15))
    except Exception:
        pass


def json_to_text(data, depth=0) -> str:
    if depth > 8:
        return ""
    SKIP = {"image","img","photo","avatar","icon","src","href","url",
            "id","_id","slug","token","key","createdat","updatedat",
            "profilepic","picture","isactive","order","rank","status"}
    parts = []
    if isinstance(data, dict):
        for k, v in data.items():
            if str(k).lower() in SKIP:
                continue
            child = json_to_text(v, depth + 1)
            if child and len(child) > 2:
                lbl = re.sub(r"([A-Z])", r" \1", str(k)).strip().title()
                parts.append(f"{lbl}: {child}" if len(child) < 150 else f"{lbl}:\n{child}")
    elif isinstance(data, list):
        for item in data:
            child = json_to_text(item, depth + 1)
            if child:
                parts.append(child)
    elif isinstance(data, str):
        v = data.strip()
        if (v and len(v) > 2
                and not v.startswith(("http", "/static", "/_next", "data:"))
                and not v.endswith((".png",".jpg",".svg",".webp",".gif",".ico"))):
            return v
    elif isinstance(data, (int, float, bool)):
        return str(data)
    return "\n".join(filter(None, parts))


def extract_text(html: str, url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script","style","noscript","nav","footer",
                     "header","aside","form","iframe","svg"]):
        tag.decompose()
    main = (
        soup.find("main") or
        soup.find("article") or
        soup.find(id=re.compile(r"content|main|article|mw-content", re.I)) or
        soup.find(class_=re.compile(r"content|main|article|post|entry|faculty|profile|card", re.I)) or
        soup.body
    )
    parts = []
    if main:
        for el in main.find_all(["p","h1","h2","h3","h4","h5","h6",
                                  "li","td","th","pre","blockquote","span","div","a"]):
            if el.name in ("div","span","a") and el.find(["p","h1","h2","h3","li","div"]):
                continue
            t = el.get_text(separator=" ", strip=True)
            if t and len(t) > 10:
                parts.append(t)
    text = "\n\n".join(parts)
    if not text or len(text) < 300:
        if soup.body:
            text = soup.body.get_text(separator="\n", strip=True)
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = re.sub(r"[ \t]{2,}", " ", text)
    title  = soup.find("title")
    header = f"Page: {title.get_text(strip=True)}\nURL: {url}\n\n" if title else f"URL: {url}\n\n"
    full   = header + text.strip()
    return full if len(full) > 150 else ""


def extract_links(html: str, base_url: str, domain: str) -> list:
    soup  = BeautifulSoup(html, "lxml")
    links = set()
    for a in soup.find_all("a", href=True):
        url = normalise_url(a["href"], base_url)
        if url and urlparse(url).netloc == domain and not should_skip(url):
            links.add(url)
    return list(links)


async def scrape_one(url: str, context) -> tuple[str, list]:
    api_texts = []
    page = await context.new_page()
    await stealth_async(page)

    async def on_response(response):
        try:
            rurl = response.url
            ct   = response.headers.get("content-type", "")
            if "json" in ct and not any(x in rurl for x in [
                    "_next","webpack","analytics","gtag","facebook","google","hotjar"]):
                body = await response.text()
                if len(body) > 30:
                    data = json.loads(body)
                    text = json_to_text(data)
                    if len(text) > 80:
                        print(f"[crawler] API: {rurl[:70]} → {len(text)} chars")
                        api_texts.append(f"[API: {rurl}]\n{text}")
        except Exception:
            pass

    page.on("response", on_response)
    html = ""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT)
        await asyncio.sleep(rnd(1.5, 2.5))
        await human_mouse(page)
        await human_scroll(page)
        await asyncio.sleep(API_WAIT)
        await human_scroll(page)
        await asyncio.sleep(rnd(1.0, 2.0))
        html = await page.content()
        if detect_captcha(html):
            print(f"[crawler] CAPTCHA at {url}")
            html = ""
    except PlaywrightTimeout:
        print(f"[crawler] Timeout: {url}")
    except Exception as e:
        print(f"[crawler] Error {url}: {e}")
    finally:
        await page.close()
    return html, api_texts


def _upsert_chunks(text, url, domain, doc_type, all_chunks, all_ids, all_metas):
    chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
    if chunks:
        print(f"[crawler] +{len(chunks)} chunks from {url}")
    for i, chunk in enumerate(chunks):
        cid = make_chunk_id(url, len(all_chunks) + i)
        all_chunks.append(chunk)
        all_ids.append(cid)
        all_metas.append({
            "source":      f"web::{domain}",
            "page_url":    url,
            "doc_type":    doc_type,
            "chunk_index": len(all_chunks) + i,
            "domain":      domain,
        })


async def crawl_and_ingest(url: str, doc_type: str = "web") -> dict:
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    domain     = urlparse(url).netloc
    queue      = deque([url])
    visited    = set([url])
    all_chunks = []
    all_ids    = []
    all_metas  = []
    pages_done = []
    pages_fail = []

    print(f"[crawler] ══ Starting full crawl: {url} ══")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage","--disable-infobars"]
        )
        context = await browser.new_context(
            user_agent=get_ua(), viewport=get_vp(),
            java_script_enabled=True, locale="en-US",
            timezone_id="Asia/Kolkata",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "DNT": "1",
            }
        )

        while queue and len(pages_done) + len(pages_fail) < MAX_PAGES:
            current = queue.popleft()
            if pages_done or pages_fail:
                await asyncio.sleep(rnd())

            print(f"[crawler] ({len(pages_done)+1}/{len(visited)}) {current}")
            html, api_texts = await scrape_one(current, context)

            if not html:
                pages_fail.append(current)
                continue

            # Discover new links
            new_links = extract_links(html, current, domain)
            added = 0
            for link in new_links:
                if link not in visited and len(visited) < MAX_PAGES * 2:
                    visited.add(link)
                    queue.append(link)
                    added += 1
            if added:
                print(f"[crawler] +{added} links discovered (queue: {len(queue)})")

            stored = False
            for at in api_texts:
                if len(at) > 100:
                    _upsert_chunks(at, current, domain, doc_type,
                                   all_chunks, all_ids, all_metas)
                    stored = True

            if not stored:
                text = extract_text(html, current)
                if text:
                    _upsert_chunks(text, current, domain, doc_type,
                                   all_chunks, all_ids, all_metas)
                    stored = True

            if stored:
                pages_done.append(current)
            else:
                pages_fail.append(current)

            print(f"[crawler] Progress: {len(pages_done)} done | {len(queue)} queued | {len(all_chunks)} chunks")

        await browser.close()

    if not all_chunks:
        return {"error": "No content extracted.", "pages_scraped": 0, "chunks_stored": 0}

    # Embed and upsert to Pinecone in batches
    print(f"[crawler] ══ Embedding {len(all_chunks)} chunks...")
    embeddings = embedder.encode(all_chunks, show_progress_bar=True).tolist()

    vectors = []
    for i, (chunk, emb, meta) in enumerate(zip(all_chunks, embeddings, all_metas)):
        vectors.append({
            "id":     all_ids[i],
            "values": emb,
            "metadata": {**meta, "text": chunk[:1000]},
        })

    batch_size = 100
    for i in range(0, len(vectors), batch_size):
        pine_index.upsert(vectors=vectors[i:i+batch_size], namespace=DOCS_NAMESPACE)
        print(f"[crawler] Upserted batch {i//batch_size + 1}/{(len(vectors)-1)//batch_size + 1}")

    print(f"[crawler] ══ DONE: {len(all_chunks)} chunks / {len(pages_done)} pages ══")
    return {
        "url":           url,
        "domain":        domain,
        "pages_scraped": len(pages_done),
        "pages_failed":  len(pages_fail),
        "chunks_stored": len(all_chunks),
        "doc_type":      "web",
        "source":        f"web::{domain}",
    }


def crawl_url_sync(url: str, doc_type: str = "web") -> dict:
    try:
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(crawl_and_ingest(url, doc_type))
        loop.close()
        return result
    except Exception as e:
        print(f"[crawler] sync error: {e}")
        return {"error": str(e), "pages_scraped": 0, "chunks_stored": 0}