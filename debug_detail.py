"""Debug script to inspect job detail page HTML structure."""
import requests
import re
from bs4 import BeautifulSoup

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

url = "https://www.brightermonday.co.ke/listings/financial-accountant-20pjqj"
resp = requests.get(url, headers=headers, timeout=30)
soup = BeautifulSoup(resp.text, "lxml")

print(f"Status: {resp.status_code}, Length: {len(resp.text)}")

# Title
h1 = soup.find("h1")
print(f"\nh1: {h1.get_text(strip=True) if h1 else 'NOT FOUND'}")
if h1:
    print(f"  h1 class: {h1.get('class', [])}")
    p = h1.parent
    for d in range(3):
        if p:
            print(f"  h1 parent[{d}]: <{p.name}> class={p.get('class', [])}")
            p = p.parent

# Company (h2)
h2_all = soup.find_all("h2")
print(f"\nh2 tags: {len(h2_all)}")
for h2 in h2_all[:5]:
    text = h2.get_text(strip=True)[:60]
    cls = h2.get("class", [])
    print(f"  h2: '{text}' class={cls}")
    link = h2.find("a")
    if link:
        print(f"    link href={link.get('href')}")

# h3 tags (section headings)
h3_all = soup.find_all("h3")
print(f"\nh3 tags: {len(h3_all)}")
for h3 in h3_all:
    text = h3.get_text(strip=True)[:60]
    cls = h3.get("class", [])
    print(f"  h3: '{text}' class={cls}")

# Job Summary container
summary_h = soup.find(lambda t: t.name in ("h3", "h2") and "job summary" in t.get_text(strip=True).lower())
if summary_h:
    print(f"\nJob Summary heading found: <{summary_h.name}>")
    container = summary_h.find_parent("div")
    if container:
        cls = container.get("class", [])
        print(f"  Container class: {cls}")
        # Show children
        for child in list(container.children)[:10]:
            if hasattr(child, "name"):
                print(f"  child: <{child.name}> class={child.get('class',[])} text={child.get_text(strip=True)[:80]}")

# Job Descriptions container
desc_h = soup.find(lambda t: t.name in ("h3", "h2") and "job description" in t.get_text(strip=True).lower())
if desc_h:
    print(f"\nJob Descriptions heading found: <{desc_h.name}>")
    container = desc_h.find_parent("div")
    if container:
        cls = container.get("class", [])
        print(f"  Container class: {cls}")
        # Show first-level children
        for child in list(container.children)[:15]:
            if hasattr(child, "name") and child.name:
                txt = child.get_text(strip=True)[:100]
                print(f"  child: <{child.name}> class={child.get('class',[])} text={txt}")

# Tags area - look for location, employment type etc.
# Find links near the top
print("\n--- Links in first section ---")
top_section = soup.find("div", class_=re.compile(r"listing|detail|header"))
if not top_section:
    # Find the area near h1
    if h1:
        top_section = h1.find_parent("div")

# Find all meaningful tags
for text_pat in ["Nairobi", "Full Time", "Confidential", "KSh", "Today", "Easy apply", "Featured"]:
    found = soup.find_all(string=re.compile(re.escape(text_pat)))
    if found:
        first = found[0]
        p = first.parent
        print(f"\n'{text_pat}' found in <{p.name if p else '?'}> class={p.get('class', []) if p and hasattr(p, 'get') else []}")
        if p and p.parent:
            print(f"  parent: <{p.parent.name}> class={p.parent.get('class', [])}")

# Save full detail HTML
with open("debug_detail_page.html", "w", encoding="utf-8") as f:
    f.write(resp.text[:80000])
print("\nSaved to debug_detail_page.html")
