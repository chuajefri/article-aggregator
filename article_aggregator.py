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
                'https://openai.com/blog/rss.xml',
                'https://www.lennysnewsletter.com/feed'
            ],
            'Health': [
                'https://www.medicalnewstoday.com/feeds/news.xml',
                'https://www.mobihealthnews.com/feed/',
                'https://www.fiercehealthcare.com/rss.xml',
                'https://medcitynews.com/feed/'
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
        """Extract main content from article URL with better parsing"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            response = requests.get(url, timeout=20, headers=headers)
            response.raise_for_status()  # Raise exception for bad status codes
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove unwanted elements more comprehensively
            unwanted_selectors = [
                'script', 'style', 'nav', 'header', 'footer', 'sidebar', 
                'advertisement', 'ads', '.ad', '.advertisement', '.sidebar',
                '.related-posts', '.comments', '.social-share', '.newsletter',
                '.popup', '.modal', '.cookie-notice', '.breadcrumb', '.tags',
                '.author-bio', '.post-meta', '.share-buttons', '[role="complementary"]'
            ]
            
            for selector in unwanted_selectors:
                for element in soup.select(selector):
                    element.decompose()
            
            # Try multiple content selectors in order of preference
            content_selectors = [
                # MedCity News specific
                '.entry-content',
                '.post-content', 
                '.article-content',
                '.content-area .content',
                
                # General article selectors
                'article .content',
                'article',
                '[role="main"]',
                '.main-content',
                '.post-body',
                '.story-body',
                'main',
                '.content',
                
                # Fallback selectors
                '#content',
                '.page-content',
                '.single-content'
            ]
            
            content = ""
            content_element = None
            
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    # Get the element with the most text content
                    content_element = max(elements, key=lambda x: len(x.get_text().strip()))
                    raw_content = content_element.get_text()
                    
                    # Only use if it has substantial content
                    if len(raw_content.strip()) > 200:
                        content = raw_content
                        print(f"Content found using selector: {selector} (length: {len(content)})")
                        break
            
            # Fallback: try to get content from paragraphs
            if not content or len(content.strip()) < 200:
                paragraphs = soup.find_all('p')
                if paragraphs:
                    content = '\n'.join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 30])
                    print(f"Content found using paragraphs fallback (length: {len(content)})")
            
            # Final fallback to body content
            if not content or len(content.strip()) < 200:
                content = soup.get_text()
                print(f"Using body fallback (length: {len(content)})")
            
            if not content:
                print(f"No content found for {url}")
                return ""
            
            # Clean up the text more thoroughly
            lines = []
            for line in content.splitlines():
                line = line.strip()
                # Filter out very short lines, navigation items, and common website elements
                if (len(line) > 15 and 
                    not line.lower().startswith(('menu', 'search', 'subscribe', 'newsletter', 'follow us', 'share')) and
                    not line.isdigit() and 
                    '©' not in line):
                    lines.append(line)
            
            clean_content = '\n'.join(lines)
            
            # Return more content for better AI processing (increase from 4000 to 6000)
            final_content = clean_content[:6000] if clean_content else ""
            print(f"Final content length for {url}: {len(final_content)}")
            
            return final_content
            
        except requests.exceptions.RequestException as e:
            print(f"Request error scraping {url}: {e}")
            return ""
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return ""

    def try_groq_free(self, content, title):
        """Try Groq free API with enhanced prompt"""
        try:
            groq_key = os.getenv('GROQ_API_KEY')
            if not groq_key:
                print("No GROQ API key found")
                return None
            
            # Early validation of content
            if not content or len(content.strip()) < 100:
                print(f"Content too short for GROQ processing: {len(content) if content else 0} characters")
                return None
            
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            }
            
            # Enhanced system prompt with clearer instructions
            system_prompt = """You are an expert healthcare and technology business analyst. Your job is to read articles and create executive summaries that highlight:

1. Key business metrics, numbers, and data points (revenue, funding, user numbers, growth %, market size, etc.)
2. Strategic business decisions and their impact on the market or patients
3. Technology innovations and their practical applications
4. Market trends, competitive positioning, and regulatory developments

FORMATTING RULES:
- Create exactly 3-4 bullet points
- Each bullet point should be 20-35 words
- Start each bullet with the most important number, company name, or key insight
- Focus on business impact and quantifiable outcomes
- Use active voice and specific details
- Avoid generic statements

EXAMPLE FORMAT:
• DUOS raised $30M Series A to serve Medicare Advantage plans, targeting 82M older adults by 2050
• Partnership with Humana expands veteran senior support services through automated SNAP-EBT application processing
• Technology automates health-related social needs coverage, reducing care navigation complexity for aging population"""

            # Truncate content strategically - keep beginning and key sections
            content_preview = content[:4000]  # Increased from 3000
            
            payload = {
                "model": "mixtral-8x7b-32768",  # Using the larger context model
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user", 
                        "content": f"""Analyze this healthcare/technology article and create a 3-4 bullet executive summary focusing on key business insights, funding, partnerships, and quantifiable impact:

TITLE: {title}

ARTICLE CONTENT:
{content_preview}

Create an executive summary with 3-4 bullet points highlighting the most important business and technology insights:"""
                    }
                ],
                "max_tokens": 400,  # Increased token limit
                "temperature": 0.2,  # Even lower for more consistent, factual output
                "top_p": 0.95
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=45)
            
            if response.status_code == 200:
                result = response.json()
                summary = result['choices'][0]['message']['content']
                print(f"GROQ raw response: {summary}")
                formatted_summary = self.clean_and_format_summary(summary)
                print(f"GROQ formatted summary: {formatted_summary}")
                return formatted_summary
            else:
                print(f"Groq API Error: {response.status_code} - {response.text}")
            
        except Exception as e:
            print(f"Groq API error: {e}")
        
        return None

    def clean_and_format_summary(self, summary_text):
        """Clean and format the AI-generated summary with better parsing"""
        if not summary_text:
            return ""
        
        print(f"Cleaning summary: {summary_text}")
        
        # Remove common AI response prefixes
        prefixes_to_remove = [
            "Here are the key points:",
            "Here's a summary:",
            "Executive Summary:",
            "Summary:",
            "Key insights:",
            "Here are 3-4 bullet points:",
            "Based on the article:"
        ]
        
        cleaned_text = summary_text
        for prefix in prefixes_to_remove:
            if cleaned_text.lower().startswith(prefix.lower()):
                cleaned_text = cleaned_text[len(prefix):].strip()
        
        # Split into lines and find bullet points
        lines = cleaned_text.split('\n')
        bullets = []
        
        for line in lines:
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
                
            # Look for various bullet formats
            bullet_patterns = ['•', '-', '*', '▪', '○']
            is_bullet = any(line.startswith(pattern) for pattern in bullet_patterns)
            is_numbered = any(line.startswith(f"{i}.") for i in range(1, 10))
            
            if is_bullet or is_numbered:
                # Clean up the bullet point
                clean_line = line
                for pattern in bullet_patterns + [f"{i}." for i in range(1, 10)]:
                    if clean_line.startswith(pattern):
                        clean_line = clean_line[len(pattern):].strip()
                        break
                
                # Only include substantial bullet points
                if len(clean_line) > 20:
                    bullets.append(f"• {clean_line}")
            elif len(line) > 30 and len(bullets) < 4:
                # If it's a substantial line without bullet formatting, add it as a bullet
                bullets.append(f"• {line}")
        
        # If we still don't have good bullets, try sentence splitting
        if len(bullets) < 2:
            sentences = summary_text.replace('\n', ' ').split('.')
            bullets = []
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) > 25 and len(bullets) < 4:
                    bullets.append(f"• {sentence}")
        
        result = '\n'.join(bullets[:4])
        print(f"Final formatted result: {result}")
        return result

    def try_openai_free(self, content, title):
        """Try OpenAI free API if available"""
        # Placeholder for OpenAI implementation
        return None

    def try_hf_chat_model(self, content, title):
        """Try Hugging Face chat model"""
        # Placeholder for Hugging Face implementation
        return None

    def generate_summary_free(self, content, title):
        """Generate summary using free AI service with better validation"""
        print(f"Generating summary for: {title}")
        print(f"Content length: {len(content) if content else 0}")
        
        # Better content validation
        if not content or len(content.strip()) < 50:
            print("Content too short, using title-based summary")
            return f"• {title}\n• Article content could not be extracted for detailed analysis"
        
        try:
            # Try Method 1: Groq (fastest, great free tier)
            summary = self.try_groq_free(content, title)
            if summary and len(summary.strip()) > 50:
                return summary
            
            # Try Method 2: OpenAI Free Tier (if available)
            summary = self.try_openai_free(content, title)
            if summary and len(summary.strip()) > 50:
                return summary
            
            # Try Method 3: Hugging Face Chat Model (supports prompts)
            summary = self.try_hf_chat_model(content, title)
            if summary and len(summary.strip()) > 50:
                return summary
                
        except Exception as e:
            print(f"Error generating summary: {e}")
        
        # Fallback: enhanced simple extraction
        return self.enhanced_simple_summary(content, title)

    def enhanced_simple_summary(self, content, title):
        """Enhanced fallback summary method"""
        if not content or len(content.split()) < 20:
            return f"• {title}\n• Content extraction failed - manual review needed"
        
        # Try to extract key sentences that contain numbers, companies, or important keywords
        sentences = content.replace('\n', ' ').split('.')
        key_sentences = []
        
        important_keywords = ['million', 'billion', 'percent', '%', '$', 'funding', 'raised', 'partnership', 'launched', 'announced']
        
        for sentence in sentences:
            sentence = sentence.strip()
            if (len(sentence) > 30 and 
                any(keyword.lower() in sentence.lower() for keyword in important_keywords)):
                key_sentences.append(sentence)
                if len(key_sentences) >= 3:
                    break
        
        # If no key sentences found, use first few sentences
        if not key_sentences:
            key_sentences = [s.strip() for s in sentences[:3] if len(s.strip()) > 30]
        
        bullets = [f"• {sentence}" for sentence in key_sentences[:3]]
        
        if not bullets:
            return f"• {title}\n• Full article content available but requires manual summary"
        
        return '\n'.join(bullets)
        
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
