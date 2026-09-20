#!/usr/bin/env python3
"""
Scraper for LDS General Conference talks.
Downloads text content from all talks and saves as JSON.
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import os
from urllib.parse import urljoin, urlparse
import re
from datetime import datetime


class ConferenceTalkScraper:
    def __init__(self, base_url="https://www.churchofjesuschrist.org", lang="eng"):
        self.base_url = base_url
        self.lang = lang
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.delay = 1  # Be respectful with requests
    
    def get_page(self, url):
        """Fetch a page with error handling and rate limiting."""
        try:
            time.sleep(self.delay)
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            response.encoding = 'utf-8'
            return response.text
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def parse_conference_list(self, html):
        """Parse the main conference page to get all conference URLs.
        Excludes speaker and topic links - only includes semiannual conference links.
        """
        soup = BeautifulSoup(html, 'html.parser')
        conference_links = []
        
        # Find all links that match the conference pattern
        for link in soup.find_all('a', href=True):
            href = link['href']
            
            # Skip speaker and topic links - we only want semiannual conferences
            if '/speakers/' in href or '/topics/' in href:
                continue
            
            # Match patterns like /study/general-conference/2025/10 or /study/general-conference/20102019
            if '/study/general-conference/' in href:
                full_url = urljoin(self.base_url, href)
                # Ensure we include lang parameter
                if '?lang=' not in full_url:
                    full_url = f"{full_url}?lang={self.lang}"
                conference_links.append(full_url)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_links = []
        for link in conference_links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)
        
        return unique_links
    
    def parse_decade_page(self, html):
        """Parse a decade page (like 2010-2019) to get individual conference URLs."""
        soup = BeautifulSoup(html, 'html.parser')
        conference_urls = []
        
        # Look for links to individual conferences
        for link in soup.find_all('a', href=True):
            href = link['href']
            # Match individual conference URLs like /study/general-conference/2019/10
            match = re.search(r'/study/general-conference/(\d{4})/(\d{1,2})', href)
            if match:
                full_url = urljoin(self.base_url, href)
                if '?lang=' not in full_url:
                    full_url = f"{full_url}?lang={self.lang}"
                conference_urls.append(full_url)
        
        return conference_urls
    
    def parse_conference_talks(self, html):
        """Parse a conference page to get all talk URLs."""
        soup = BeautifulSoup(html, 'html.parser')
        talk_urls = []
        
        # Find all links that are talks
        # Talks are typically in navigation links or content sections
        for link in soup.find_all('a', href=True):
            href = link['href']
            # Match talk URLs like /study/general-conference/2025/10/[talk-slug]
            # These have the pattern /study/general-conference/YEAR/MONTH/[title]
            # Exclude session links like "saturday-morning-session"
            if '/study/general-conference/' in href:
                # Match: year/month/talk-slug (can have hyphens)
                match = re.search(r'/study/general-conference/(\d{4})/(\d{1,2})/([a-z0-9-]+)', href)
                if match:
                    talk_slug = match.group(3)
                    # Skip session links (which contain "session" in the slug)
                    if 'session' not in talk_slug:
                        full_url = urljoin(self.base_url, href)
                        if '?lang=' not in full_url:
                            full_url = f"{full_url}?lang={self.lang}"
                        talk_urls.append(full_url)
        
        # Remove duplicates
        return list(set(talk_urls))
    
    NOTE_OPEN, NOTE_CLOSE = "\ue000", "\ue001"   # private-use sentinels for footnote markers

    def paragraph_text(self, p):
        """Text of a paragraph with whitespace collapsed, plus the footnote markers
        that occur in it as (note number, character offset) pairs.

        The site renders a footnote marker as <a class="note-ref"><sup data-value="N"/></a>
        with no text, so we drop a sentinel in its place, normalise whitespace, then
        pull the sentinels back out and remember where they were."""
        for a in p.find_all("a", class_="note-ref"):
            sup = a.find("sup")
            n = (sup.get("data-value") if sup else None) or re.sub(r"\D", "", a.get("href", ""))
            a.replace_with(f"{self.NOTE_OPEN}{n}{self.NOTE_CLOSE}" if n else "")
        text = " ".join(p.get_text().split())
        refs, out, i = [], [], 0
        while True:
            j = text.find(self.NOTE_OPEN, i)
            if j < 0:
                out.append(text[i:])
                break
            k = text.find(self.NOTE_CLOSE, j)
            out.append(text[i:j])
            clean_pos = sum(len(x) for x in out)
            try:
                refs.append({"n": int(text[j + 1:k]), "pos": clean_pos})
            except ValueError:
                pass
            i = k + 1
        clean = "".join(out)
        # a marker glued to a preceding space leaves a double space; tidy without moving offsets much
        return clean.strip(), refs

    def extract_notes(self, content_div):
        """Pull the endnotes out of <footer class="notes"> and remove the footer from the tree."""
        footer = content_div.find("footer", class_="notes")
        if not footer:
            return []
        notes = []
        for li in footer.find_all("li", id=re.compile(r"^note\d+$")):
            marker = (li.get("data-marker") or li["id"][4:]).rstrip(".")
            try:
                n = int(marker)
            except ValueError:
                continue
            paras = [" ".join(q.get_text().split()) for q in li.find_all("p")] or [" ".join(li.get_text().split())]
            text = "\n".join(x for x in paras if x)
            if text:
                notes.append({"n": n, "text": text})
        footer.decompose()
        return notes

    def extract_talk_content(self, html):
        """Extract text content from a talk page.

        Returns speaker, title, body paragraphs (with footnote-marker positions)
        and the endnotes as a separate list."""
        soup = BeautifulSoup(html, 'html.parser')

        content_div = soup.find('div', class_='body')
        if not content_div:
            content_div = soup.find('div', class_=re.compile('body-block|content'))
        if not content_div:
            return None

        notes = self.extract_notes(content_div)

        paragraphs, note_refs = [], []
        for p in content_div.find_all('p'):
            text, refs = self.paragraph_text(p)
            # Skip empty paragraphs or very short ones (likely metadata)
            if text and len(text) > 5:
                paragraphs.append(text)
                note_refs.append(refs)

        speaker = None
        for text in paragraphs[:5]:
            if text.startswith('By '):
                speaker = text.replace('By ', '').strip()
                break
        if not speaker:
            speaker_elem = soup.find('meta', {'property': 'article:author'})
            if speaker_elem:
                speaker = speaker_elem.get('content')

        title_elem = soup.find('h1')
        title = title_elem.get_text(strip=True) if title_elem else None

        return {
            'speaker': speaker or '',
            'title': title or '',
            'content': '\n\n'.join(paragraphs),
            'paragraphs': paragraphs,
            'note_refs': note_refs,
            'notes': notes,
        }

    def scrape_conference(self, conference_url):
        """Scrape all talks from a single conference."""
        print(f"\nScraping conference: {conference_url}")
        html = self.get_page(conference_url)
        if not html:
            return []
        
        talk_urls = self.parse_conference_talks(html)
        print(f"Found {len(talk_urls)} talks")
        
        talks = []
        for i, talk_url in enumerate(talk_urls, 1):
            print(f"  [{i}/{len(talk_urls)}] Fetching: {talk_url}")
            talk_html = self.get_page(talk_url)
            if talk_html:
                talk_data = self.extract_talk_content(talk_html)
                if talk_data:
                    talk_data['url'] = talk_url
                    talks.append(talk_data)
        
        return talks
    
    def save_incremental(self, output_file, all_conferences):
        """Save current progress to JSON file incrementally."""
        structured_data = {
            'metadata': {
                'scraped_date': datetime.now().isoformat(),
                'total_conferences': len(all_conferences),
                'total_talks': sum(len(talks) for talks in all_conferences.values())
            },
            'conferences': {}
        }
        
        for conf_url, talks in all_conferences.items():
            structured_data['conferences'][conf_url] = {
                'url': conf_url,
                'talk_count': len(talks),
                'talks': talks
            }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(structured_data, f, indent=2, ensure_ascii=False)
    
    def scrape_all(self, start_url, output_file=None, existing=None):
        """Scrape all conferences starting from the main page.

        If `existing` (a dict of conference_url -> talks) is given, conferences
        already present are skipped and new ones are merged into it.
        """
        print("Starting scrape...")
        
        # Get the main page
        html = self.get_page(start_url)
        if not html:
            print("Failed to fetch main page")
            return {}
        
        # Parse to get all conference links
        conference_links = self.parse_conference_list(html)
        print(f"Found {len(conference_links)} conference links on main page")
        
        all_conferences = dict(existing) if existing else {}
        skipped = 0
        
        # Save incrementally if output file is provided
        save_progress = output_file is not None
        
        for conf_url in conference_links:
            # Check if this is a decade page or individual conference
            # Decade pages have 8-digit pattern like /20102019 followed by ? or end of string
            if re.search(r'/\d{8}(?:\?|$)', conf_url):  # Like 20102019
                print(f"\nProcessing decade page: {conf_url}")
                decade_html = self.get_page(conf_url)
                if decade_html:
                    individual_confs = self.parse_decade_page(decade_html)
                    print(f"  Found {len(individual_confs)} individual conferences")
                    for ind_conf_url in individual_confs:
                        if ind_conf_url in all_conferences:
                            skipped += 1
                            continue
                        talks = self.scrape_conference(ind_conf_url)
                        if talks:
                            all_conferences[ind_conf_url] = talks
                            # Save after each conference
                            if save_progress:
                                self.save_incremental(output_file, all_conferences)
                                print(f"  ✓ Progress saved ({len(all_conferences)} conferences, {sum(len(t) for t in all_conferences.values())} talks)")
            else:
                # Individual conference
                if conf_url in all_conferences:
                    skipped += 1
                    continue
                talks = self.scrape_conference(conf_url)
                if talks:
                    all_conferences[conf_url] = talks
                    # Save after each conference
                    if save_progress:
                        self.save_incremental(output_file, all_conferences)
                        print(f"  ✓ Progress saved ({len(all_conferences)} conferences, {sum(len(t) for t in all_conferences.values())} talks)")
        
        if skipped:
            print(f"\nSkipped {skipped} conferences already present in existing data")
        return all_conferences


def load_existing(output_file):
    """Load previously scraped conferences as a dict of url -> talks."""
    if not os.path.exists(output_file):
        return {}
    with open(output_file, encoding='utf-8') as f:
        data = json.load(f)
    return {url: conf['talks'] for url, conf in data.get('conferences', {}).items()}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Scrape LDS General Conference talks to JSON.")
    parser.add_argument('--update', action='store_true',
                        help="Only scrape conferences not already in the output file")
    parser.add_argument('--refresh', nargs='+', metavar='YYYY/MM',
                        help="Re-scrape these conferences (e.g. 2026/04) and replace them in the output file")
    parser.add_argument("--output", default="data/general_conference_talks.json")
    args = parser.parse_args()

    base_url = "https://www.churchofjesuschrist.org/study/general-conference"
    start_url = f"{base_url}?lang=eng"
    
    scraper = ConferenceTalkScraper()
    output_file = args.output
    if args.refresh:
        existing = load_existing(output_file)
        for conf in args.refresh:
            url = f"{base_url}/{conf}?lang=eng"
            talks = scraper.scrape_conference(url)
            if talks:
                existing[url] = talks
                scraper.save_incremental(output_file, existing)
                print(f"  ✓ Refreshed {conf}: {len(talks)} talks")
        return

    existing = None
    if args.update:
        existing = load_existing(output_file)
        print(f"Update mode: {len(existing)} conferences already in {output_file}")
    
    print("Starting conference talk scraper...")
    print(f"Progress will be saved incrementally to: {output_file}")
    print("(The file will be updated after each conference is scraped)\n")
    
    all_data = scraper.scrape_all(start_url, output_file=output_file, existing=existing)
    
    # Final save (in case anything changed)
    scraper.save_incremental(output_file, all_data)
    
    total_talks = sum(len(talks) for talks in all_data.values())
    print(f"\n✓ Complete! Saved {total_talks} talks from {len(all_data)} conferences to {output_file}")


if __name__ == "__main__":
    main()

