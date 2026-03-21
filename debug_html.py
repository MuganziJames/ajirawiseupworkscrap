"""Quick debug script to inspect BrighterMonday HTML structure."""
import requests
import re
from bs4 import BeautifulSoup

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

resp = requests.get("https://www.brightermonday.co.ke/jobs", headers=headers, timeout=30)
soup = BeautifulSoup(resp.text, "lxml")

print(f"Status: {resp.status_code}")
print(f"Page length: {len(resp.text)}")

# Find all links to /listings/
listing_links = soup.find_all("a", href=re.compile(r"/listings/"))
print(f"\nFound {len(listing_links)} listing links")

for i, link in enumerate(listing_links[:5]):
    href = link.get("href", "")
    text = link.get_text(strip=True)[:60]
    print(f"\n  [{i}] href={href}")
    print(f"      text={text}")
    # Show parent chain classes
    p = link.parent
    depth = 0
    while p and depth < 6:
        cls = p.get("class", []) if hasattr(p, "get") else []
        tag = p.name if hasattr(p, "name") else "?"
        print(f"      parent[{depth}]: <{tag}> class={cls}")
        p = p.parent
        depth += 1

# Also check page numbers
page_links = soup.find_all("a", href=re.compile(r"page=\d+"))
print(f"\nPagination links: {len(page_links)}")
for pl in page_links[:3]:
    print(f"  {pl.get('href')}")

# Check for any article or div with search-result class
articles = soup.find_all("article")
print(f"\n<article> tags: {len(articles)}")

# Check for common card containers
for cls_pattern in ["search-result", "job-card", "listing-card", "job-list", "card"]:
    found = soup.find_all(class_=re.compile(cls_pattern, re.IGNORECASE))
    print(f"class~={cls_pattern}: {len(found)} elements")

# Save raw HTML for inspection
with open("debug_listing_page.html", "w", encoding="utf-8") as f:
    f.write(resp.text[:50000])
print("\nSaved first 50KB of HTML to debug_listing_page.html")
