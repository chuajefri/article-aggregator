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
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, timeout=15, headers=headers)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'sidebar', 'advertisement', 'ads']):
                element.decompose()
            
            # Try multiple selectors to find main content
            content_selectors = [
                'article',
                '[role="main"]',
                '.post-content',
                '.entry-content', 
                '.article-content',
                '.content',
                '.post-body',
                '.story-body',
                'main',
                '.main-content'
            ]
            
            content = ""
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    # Get the largest element (likely the main content)
                    main_element = max(elements, key=lambda x: len(x.get_text()))
                    content = main_element.get_text()
                    break
            
            # Fallback to body if no specific content found
            if not content:
                content = soup.get_text()
            
            # Clean up the text
            lines = (line.strip() for line in content.splitlines())
            paragraphs = (line for line in lines if line and len(line) > 20)  # Filter short lines
            clean_content = '\n'.join(paragraphs)
            
            # Return first 4000 characters for better context
            return clean_content[:4000] if clean_content else ""
            
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return ""
    
    def generate_summary_free(self, content, title):
        """Generate summary using free AI service with custom prompt"""
        try:
            # Try Method 1: Groq (fastest, great free tier)
            summary = self.try_groq_free(content, title)
            if summary:
                return summary
            
            # Try Method 2: OpenAI Free Tier (if available)
            summary = self.try_openai_free(content, title)
            if summary:
                return summary
            
            # Try Method 3: Hugging Face Chat Model (supports prompts)
            summary = self.try_hf_chat_model(content, title)
            if summary:
                return summary
                
        except Exception as e:
            print(f"Error generating summary: {e}")
            
        # Fallback: simple extraction
        return self.simple_summary(content, title)
    
    def try_hf_chat_model(self, content, title):
        """Try using HuggingFace chat model that supports prompts"""
        try:
            # Using a smaller chat model that's free and supports prompts
            API_URL = "https://api-inference.huggingface.co/models/microsoft/DialoGPT-medium"
            headers = {"Authorization": f"Bearer {self.hf_token}"}
            
            prompt = f"""As an expert product manager, read through the article and summarize the article in 3 or 4 bullet points, highlighting key data points if any.

Article Title: {title}

Article Content: {content[:800]}

Summary:"""
            
            payload = {
                "inputs": prompt,
                "parameters": {
                    "max_new_tokens": 200,
                    "temperature": 0.7,
                    "return_full_text": False
                }
            }
            
            response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and result:
                    generated_text = result[0].get('generated_text', '')
                    return self.clean_and_format_summary(generated_text)
            else:
                print(f"HF Chat API Error: {response.status_code}")
            
        except Exception as e:
            print(f"HF Chat model error: {e}")
        
        return None
    
    def get_custom_prompt(self, prompt_style="product_manager"):
        """Get different prompt styles for summaries"""
        prompts = {
            "product_manager": """You are an expert product manager and business analyst. Create executive summaries that highlight:
1. Key business metrics, numbers, and data points (revenue, users, growth %, etc.)
2. Strategic decisions and their business impact  
3. Market trends and competitive advantages
4. Technology breakthroughs with quantifiable benefits

Format as exactly 3-4 bullet points, each 15-25 words, starting with the most important number or insight.""",

            "investor": """You are a venture capital analyst. Focus on:
1. Market size and growth opportunities
2. Competitive positioning and moats
3. Revenue models and unit economics  
4. Risk factors and regulatory concerns

Format as 3-4 bullet points highlighting investment implications.""",

            "tech_executive": """You are a CTO analyzing technical developments. Focus on:
1. Technical innovations and their business impact
2. Performance improvements with specific metrics
3. Architecture decisions and scalability implications
4. Security, compliance, and operational considerations

Format as 3-4 bullet points with technical depth and business context.""",

            "simple": """Summarize this article in 3-4 clear bullet points that anyone can understand. Focus on:
1. What happened (the main news)
2. Why it matters (the impact)
3. Key numbers or facts
4. What happens next (if mentioned)

Be specific and use numbers when available."""
        }
        
        return prompts.get(prompt_style, prompts["product_manager"])
    
    def try_groq_free(self, content, title):
        """Try Groq free API with enhanced prompt"""
        try:
            groq_key = os.getenv('GROQ_API_KEY')
            if not groq_key:
                return None
            
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            }
            
            # Enhanced prompt with specific instructions
            system_prompt = """You are an expert product manager and business analyst. Your job is to read articles and create executive summaries that highlight:

1. Key business metrics, numbers, and data points (revenue, users, growth %, etc.)
2. Strategic decisions and their business impact
3. Market trends and competitive advantages
4. Technology breakthroughs with quantifiable benefits

Format your response as exactly 3-4 bullet points. Each bullet should:
- Start with the most important insight or number
- Be specific and quantifiable when possible
- Focus on business impact, not just features
- Be concise but informative (15-25 words per bullet)

Example format:
• Revenue increased 47% to $2.1B driven by enterprise AI adoption among Fortune 500 companies
• New feature reduces customer churn by 23% through predictive analytics, saving $45M annually
• Strategic partnership with Microsoft expands market reach to 150M potential enterprise users"""

            payload = {
                "model": "mixtral-8x7b-32768",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user", 
                        "content": f"""Analyze this article and create a 3-4 bullet executive summary focusing on key business insights and data points:

TITLE: {title}

ARTICLE CONTENT:
{content[:3000]}

Executive Summary:"""
                    }
                ],
                "max_tokens": 300,
                "temperature": 0.1,  # Lower for more consistent output
                "top_p": 0.9
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                summary = result['choices'][0]['message']['content']
                return self.clean_and_format_summary(summary)
            else:
                print(f"Groq API Error: {response.status_code} - {response.text}")
            
        except Exception as e:
            print(f"Groq API error: {e}")
        
        return None
    
    def try_openai_free(self, content, title):
        """Try OpenAI free tier if available"""
        try:
            openai_key = os.getenv('OPENAI_API_KEY')  # Optional
            if not openai_key:
                return None
            
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {
                        "role": "system", 
                        "content": "You are an expert product manager. Summarize articles in exactly 3-4 bullet points, highlighting key data points."
                    },
                    {
                        "role": "user", 
                        "content": f"Article Title: {title}\n\nContent: {content[:1500]}\n\nProvide a 3-4 bullet point summary:"
                    }
                ],
                "max_tokens": 200,
                "temperature": 0.3
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                summary = result['choices'][0]['message']['content']
                return self.clean_and_format_summary(summary)
            
        except Exception as e:
            print(f"OpenAI API error: {e}")
        
        return None
    
    def clean_and_format_summary(self, summary_text):
        """Clean and format the AI-generated summary"""
        # Remove any intro text and get to the bullet points
        lines = summary_text.split('\n')
        bullets = []
        
        for line in lines:
            line = line.strip()
            # Look for bullet points or numbered items
            if (line.startswith('•') or line.startswith('-') or 
                line.startswith('*') or any(line.startswith(f"{i}.") for i in range(1, 10))):
                # Clean up the bullet point
                clean_line = line.lstrip('•-*0123456789. ').strip()
                if len(clean_line) > 15:  # Filter out very short items
                    bullets.append(f"• {clean_line}")
        
        # If we don't have proper bullets, try to split into sentences
        if len(bullets) < 2:
            sentences = summary_text.replace('\n', ' ').split('.')
            bullets = []
            for sentence in sentences[:4]:
                sentence = sentence.strip()
                if len(sentence) > 20:
                    bullets.append(f"• {sentence}")
        
        return '\n'.join(bullets[:4])
    
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
