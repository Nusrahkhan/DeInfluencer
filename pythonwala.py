from io import TextIOWrapper
import requests
import json
import csv
import time
from bs4 import BeautifulSoup

def scrape_reddit() ->list[dict]:
    subreddits = [
        "https://www.reddit.com/r/learnprogramming",
        "https://www.reddit.com/r/programming",
        "https://www.reddit.com/r/python",
    ]

    all_data = []
    for url in subreddits:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'DNT': '1'
        }

        subreddit_name = url.split('/')[-1]
        print(f"Scraping {subreddit_name}...")

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            subreddit_data = {
                "subreddit_name": subreddit_name,
                "url": url,
                "title": soup.title.string if soup.title else 'No Title',
                "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            topics = []

            for heading in soup.find_all(['h1', 'h2', 'h3']):
                text = heading.text.strip()

                if text and len(text) > 3:
                    if any(keyword in text.lower() for keyword in ['python', 'programming', 'learn', 'developer']):
                        topics.append({
                            "title": text,
                            "type": "python_topic"
                        })

            discussions = []
            seen_urls = set()

            for link in soup.find_all('a', href=True):
                text = link.get_text(strip=True)
                href = link['href']

                if text and len(text) > 1 and "/comments" in href and href not in seen_urls:
                    seen_urls.add(href)
                    discussions.append({
                        "title": text[:100] + "..." if len(text) > 100 else text,
                        "url": href,
                        "type": "discussion"
                    })

            subreddit_data["topics"] = topics
            subreddit_data["discussions"] = discussions
            all_data.append(subreddit_data)
            time.sleep(3)  # Be polite and avoid hitting Reddit too hard
        
        except Exception as e:
            print(f"Error scraping {url}: {e}")
    
    return all_data

#JSON
def save_scraped_data(data, filename="reddit_python_data.json", filename_csv="reddit__python_data.csv"):
    if not data:
        print("No data to save.")
        return
    try:
        with open(filename, "w", encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=True, indent=4)
        print(f"Data saved to {filename}")
    except Exception as e:
        print(f"Error saving JSON: {e}")

#CSV
    try:
        with open(filename_csv, "w", newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(["Subreddit", "Type", "Title", "URL", "Scraped_at"])

            for subreddit_data in data:
                subreddit = subreddit_data.get("subreddit_name", "")
                scraped_at = subreddit_data.get("scraped_at", "")

                for topic in subreddit_data.get("topics", []):
                    writer.writerow([
                        subreddit, topic['type'], topic['title'], "", scraped_at
                    ])
                for discussion in subreddit_data.get("discussions", []):
                    writer.writerow([
                        subreddit, discussion['type'], discussion['title'], discussion['url'], scraped_at
                    ])
        print(f"Data saved to {filename_csv}")
    except Exception as e:
        print(f"Error saving CSV: {e}")

def main() -> None:
    data = scrape_reddit()

    if data:
        print(f"Processing data..")
        total_topics = 0
        total_discussions = 0

        for subreddit_data in data:
            total_count = len(subreddit_data.get("topics", []))
            discussion_count = len(subreddit_data.get("discussions", []))
            total_topics += total_count
            total_discussions += discussion_count
        
        print(f"Total: {total_topics} topics, {total_discussions} discussions")
        save_scraped_data(data)

if __name__ == "__main__":
    main()