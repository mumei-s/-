from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
import json
import re
import time
from playwright.sync_api import sync_playwright

TAG_URL = "https://note.com/hashtag/%E3%82%AF%E3%83%AA%E3%82%A8%E3%82%A4%E3%82%BF%E3%83%BC%E5%9B%B3%E9%91%91?f=new"
ARTICLE_RE = re.compile(r"^https://note\.com/[^/]+/n/n[0-9a-zA-Z]+$")


def canonicalize(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def card_urls(page):
    # One URL per visible article card where possible. This avoids counting image/title links twice.
    return page.evaluate(
        """
        () => {
          const articleRe = /^https:\/\/note\.com\/[^/]+\/n\/n[0-9A-Za-z]+(?:[?#].*)?$/;
          const candidates = [];
          const seenNodes = new Set();
          const links = [...document.querySelectorAll('a[href]')].filter(a => articleRe.test(a.href));

          for (const a of links) {
            let node = a;
            for (let i = 0; i < 7 && node && node.parentElement; i++, node = node.parentElement) {
              const inner = [...node.querySelectorAll('a[href]')].filter(x => articleRe.test(x.href));
              const unique = [...new Set(inner.map(x => x.href.split(/[?#]/)[0]))];
              if (unique.length === 1 && (node.innerText || '').trim().length > 10) {
                if (!seenNodes.has(node)) {
                  seenNodes.add(node);
                  candidates.push(unique[0]);
                }
                break;
              }
            }
          }

          if (candidates.length >= 5) return candidates;

          // Fallback: keep the first occurrence of each adjacent duplicate only.
          const raw = links.map(a => a.href.split(/[?#]/)[0]);
          const out = [];
          for (const u of raw) {
            if (out.length === 0 || out[out.length - 1] !== u) out.push(u);
          }
          return out;
        }
        """
    )


def main():
    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1440, "height": 2200},
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0 Safari/537.36"
            ),
        )
        page.goto(TAG_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(3500)

        previous_count = -1
        stable_rounds = 0
        for _ in range(120):
            current = card_urls(page)
            count = len(current)

            if count == previous_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                previous_count = count

            # Prefer explicit load-more buttons if note renders one.
            clicked = False
            for label in ["もっと見る", "さらに表示", "もっと読み込む"]:
                locator = page.get_by_text(label, exact=True)
                if locator.count() > 0:
                    try:
                        locator.last.scroll_into_view_if_needed()
                        locator.last.click(timeout=2500)
                        clicked = True
                        page.wait_for_timeout(1300)
                        break
                    except Exception:
                        pass

            if not clicked:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1300)

            if stable_rounds >= 7:
                break

        urls = [canonicalize(u) for u in card_urls(page) if ARTICLE_RE.match(canonicalize(u))]
        browser.close()

    payload = {
        "tag": "#クリエイター図鑑",
        "source": TAG_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(urls),
        "urls": urls,
    }

    (out_dir / "articles.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "urls.txt").write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    print(f"Saved {len(urls)} URLs")


if __name__ == "__main__":
    main()
