"""Debug script to inspect more of the detail page structure."""
import requests
import re
from bs4 import BeautifulSoup, NavigableString

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
}

url = "https://www.brightermonday.co.ke/listings/financial-accountant-20pjqj"
resp = requests.get(url, headers=headers, timeout=30)
soup = BeautifulSoup(resp.text, "lxml")

# Job Summary container children
summary_h = soup.find(lambda t: t.name in ("h3",) and "job summary" in t.get_text(strip=True).lower())
if summary_h:
    container = summary_h.find_parent("div")
    if container:
        print("=== Job Summary Container ===")
        for child in list(container.children)[:20]:
            if isinstance(child, NavigableString):
                txt = child.strip()
                if txt:
                    print(f"  TEXT: '{txt[:80]}'")
            else:
                print(f"  <{child.name}> class={child.get('class',[])} text='{child.get_text(strip=True)[:100]}'")

# Job Descriptions container
desc_h = soup.find(lambda t: t.name in ("h3",) and "job description" in t.get_text(strip=True).lower())
if desc_h:
    container = desc_h.find_parent("div")
    if container:
        print("\n=== Job Descriptions Container ===")
        print(f"Container class: {container.get('class', [])}")
        for child in list(container.children)[:25]:
            if isinstance(child, NavigableString):
                txt = child.strip()
                if txt:
                    print(f"  TEXT: '{txt[:80]}'")
            else:
                print(f"  <{child.name}> class={child.get('class',[])} text='{child.get_text(strip=True)[:120]}'")

# Look at tags area near h1
h1 = soup.find("h1")
if h1:
    # Walk up to find the tags section
    tags_area = h1.find_parent("div", class_=re.compile(r"w-full"))
    if tags_area:
        # Find all links in this area
        print("\n=== Links near title ===")
        links = tags_area.find_all("a")
        for link in links[:15]:
            href = link.get("href", "")
            text = link.get_text(strip=True)
            if text:
                print(f"  <a href='{href}'>{text}</a>")
        # Find spans and other text
        print("\n=== Spans/badges near title ===")
        spans = tags_area.find_all("span")
        for span in spans[:15]:
            text = span.get_text(strip=True)
            cls = span.get("class", [])
            if text:
                print(f"  <span class={cls}>{text}</span>")

# Look for company logo on detail page
print("\n=== Images ===")
imgs = soup.find_all("img")
for img in imgs[:10]:
    src = img.get("src", "") or img.get("data-src", "")
    alt = img.get("alt", "")
    cls = img.get("class", [])
    if src and "logo" not in src.lower() and "static-assets" not in src:
        print(f"  <img src='{src[:100]}' alt='{alt}' class={cls}>")

# Check listing page card structure more carefully
print("\n\n========== LISTING PAGE CARD STRUCTURE ==========")
resp2 = requests.get("https://www.brightermonday.co.ke/jobs", headers=headers, timeout=30)
soup2 = BeautifulSoup(resp2.text, "lxml")

# Find the card container by the known class pattern
cards = soup2.find_all("div", class_=lambda c: c and "col-span-1" in c and "mb-5" in c)
print(f"\nFound {len(cards)} card containers with col-span-1 + mb-5")

if cards:
    card = cards[0]
    print(f"\nFirst card HTML (truncated):")
    card_html = str(card)[:3000]
    print(card_html)
