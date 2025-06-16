import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import time
import os

class ArticleAggregator:
    def __init__(self):
        self.sources = {
            'Tech': [
                'https://techcrunch.com/feed/',
                'https://www.theverge.com/rss/index.xml',
                'https://feeds.arstechnica.com/arstechnica/index',
                'https://rss.cnn.com/rss/edition_technology.rss'
            ],
            'Health': [
                'https://www.medicalnewstoday.com/feeds/news.xml',
                'https://feeds.webmd.com/rss/rss.aspx?RSSSource=RSS_PUBLIC'
            ]
        }
        # Get tokens from environment variables (GitHub Secrets)
        self.notion_token = os.getenv('NOTION_TOKEN')
        self.notion_database_id = os.getenv('NOTION_DATABASE_ID')
        self.hf_token = os.getenv('HUGGINGFACE_TOKEN')
        
    def fetch_rss_articles(self, url, hours_back=24):
        """Fetch articles from RSS feed within specified timeframe"""
        try:
            feed = feedparser.parse(url)
            recent_articles = []
            cutoff_time = datetime.now() - timedelta(hours=hours_back)
            
            for entry in feed.entries:
                # Parse publication date
                pub_date = datetime(*entry.published_parsed[:6])
                
                if pub_date > cutoff_time:
                    article = {
                        'title': entry.title,
                        'url': entry.link,
                        'published': pub_date.isoformat(),
                        'source': feed.feed.title,
                        'description': getattr(entry, 'summary', '')[:200]
                    }
                    recent_articles.append(article)
            
            return recent_articles
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return []
    
    def scrape_article_content(self, url):
        """Extract main content from article URL"""
        try:
            response = requests.get(url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Try to find main content
            content = ""
            for selector in ['article', '.content', '.post-content', 'main', '.entry-content']:
                element = soup.select_one(selector)
                if element:
                    content = element.get_text()
                    break
            
            if not content:
                content = soup.get_text()
            
            # Clean up text
            lines = (line.strip() for line in content.splitlines())
            content = '\n'.join(line for line in lines if line)
            
            return content[:2000]  # Limit for AI processing
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return ""
    
    def generate_summary_free(self, content, title):
        """Generate summary using free AI service (Hugging Face)"""
        try:
            # Using Hugging Face Inference API (free tier)
            API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
            headers = {"Authorization": f"Bearer {self.hf_token}"}
            
            # Prepare content for summarization
            text_to_summarize = f"Article: {title}\n\n{content[:1000]}"  # Limit input
            
            payload = {
                "inputs": text_to_summarize,
                "parameters": {
                    "max_length": 130,
                    "min_length": 50,
                    "do_sample": False
                }
            }
            
            response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and result:
                    summary = result[0].get('summary_text', '')
                    bullets = self.format_as_bullets(summary)
                    return bullets
            else:
                print(f"HF API Error: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"Error generating summary: {e}")
            
        # Fallback: simple extraction
        return self.simple_summary(content, title)
    
    def format_as_bullets(self, text):
        """Convert summary text to 3-4 bullet points"""
        sentences = text.split('.')
        bullets = []
        
        for sentence in sentences[:4]:
            sentence = sentence.strip()
            if len(sentence) > 20:  # Filter out very short fragments
                bullets.append(f"• {sentence}")
        
        return '\n'.join(bullets[:4])
    
    def simple_summary(self, content, title):
        """Fallback summary method"""
        words = content.split()
        if len(words) < 50:
            return f"• {title}\n• Content too short for detailed summary"
        
        # Extract first few meaningful sentences
        sentences = content.split('.')[:3]
        bullets = [f"• {sentence.strip()}" for sentence in sentences if len(sentence.strip()) > 20]
        
        return '\n'.join(bullets[:3])
    
    def add_to_notion(self, article):
        """Add article to Notion database"""
        url = f"https://api.notion.com/v1/pages"
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        
        data = {
            "parent": {"database_id": self.notion_database_id},
            "properties": {
                "Title": {
                    "title": [{"text": {"content": article['title']}}]
                },
                "URL": {
                    "url": article['url']
                },
                "Source": {
                    "rich_text": [{"text": {"content": article['source']}}]
                },
                "Published": {
                    "date": {"start": article['published']}
                },
                "Summary": {
                    "rich_text": [{"text": {"content": article['summary']}}]
                },
                "Category": {
                    "select": {"name": article['category']}
                }
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            return response.status_code == 200
        except Exception as e:
            print(f"Error adding to Notion: {e}")
            return False
    
    def run_daily_aggregation(self):
        """Main function to run daily article aggregation"""
        print(f"Starting aggregation at {datetime.now()}")
        
        all_articles = []
        
        # Fetch articles from all sources
        for category, urls in self.sources.items():
            for url in urls:
                articles = self.fetch_rss_articles(url)
                for article in articles:
                    article['category'] = category
                    
                    # Get full content and summarize
                    content = self.scrape_article_content(article['url'])
                    if content:
                        article['summary'] = self.generate_summary_free(content, article['title'])
                        all_articles.append(article)
                    
                    # Rate limiting
                    time.sleep(1)
        
        # Add to Notion
        successful = 0
        for article in all_articles:
            if self.add_to_notion(article):
                successful += 1
                print(f"Added: {article['title']}")
            time.sleep(0.5)  # Rate limiting
        
        print(f"Successfully added {successful}/{len(all_articles)} articles")
        return all_articles

# Usage
if __name__ == "__main__":
    aggregator = ArticleAggregator()
    articles = aggregator.run_daily_aggregation()
