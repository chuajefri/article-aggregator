import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import time
import os
import re

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
        """Enhanced content extraction with improved TechCrunch support"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            response = requests.get(url, timeout=20, headers=headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Enhanced unwanted elements removal
            unwanted_selectors = [
                'script', 'style', 'nav', 'header', 'footer', 'sidebar', 
                'advertisement', 'ads', '.ad', '.advertisement', '.sidebar',
                '.related-posts', '.comments', '.social-share', '.newsletter',
                '.popup', '.modal', '.cookie-notice', '.breadcrumb', '.tags',
                '.author-bio', '.post-meta', '.share-buttons', '[role="complementary"]',
                '.wp-block-group', '.entry-meta', '.post-navigation', '.author-info',
                '.related-content', '.promo', '.callout', '.embed', '.video-player',
                '.toc', '.table-of-contents', '.byline', '.dateline', '.subheading',
                '.wp-block-separator', '.wp-block-spacer', '.social-links',
                '.newsletter-signup', '.cta', '.call-to-action'
            ]
            
            for selector in unwanted_selectors:
                for element in soup.select(selector):
                    element.decompose()
            
            # Updated content selectors with more TechCrunch-specific ones
            content_selectors = [
                # TechCrunch specific (updated for 2024/2025)
                '.wp-block-post-content',
                '.entry-content',
                '.article-content',
                '.post-content',
                '.single-post-content',
                '.article-body',
                
                # General selectors
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
            used_selector = ""
            
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    # Get the element with the most text content
                    content_element = max(elements, key=lambda x: len(x.get_text().strip()))
                    raw_content = content_element.get_text()
                    
                    if len(raw_content.strip()) > 500:  # Increased threshold
                        content = raw_content
                        used_selector = selector
                        print(f"Content found using selector: {selector} (length: {len(content)})")
                        break
            
            # Enhanced paragraph fallback with better filtering
            if not content or len(content.strip()) < 500:
                print("Trying paragraph extraction...")
                article_paragraphs = soup.select('article p, .post-content p, .entry-content p, .article-content p, .wp-block-post-content p')
                if not article_paragraphs:
                    article_paragraphs = soup.find_all('p')
                
                if article_paragraphs:
                    valid_paragraphs = []
                    for p in article_paragraphs:
                        p_text = p.get_text().strip()
                        # More comprehensive filtering
                        skip_phrases = [
                            'subscribe', 'newsletter', 'follow us', 'share this',
                            'read more', 'continue reading', 'advertisement',
                            'sponsored', 'getty images', 'image credit',
                            'techcrunch', 'crunchbase', 'save', 'menu',
                            'build smarter', 'looking back', 'what do you feel',
                            'all rights reserved', 'privacy policy', 'terms of service',
                            'cookie policy', 'contact us', 'about us'
                        ]
                        
                        if (len(p_text) > 50 and 
                            not any(skip in p_text.lower() for skip in skip_phrases) and
                            not p_text.lower().startswith('image:') and
                            not p_text.lower().startswith('photo:') and
                            not re.match(r'^\d+\s*(min|hour|day|week|month|year)', p_text.lower())):
                            valid_paragraphs.append(p_text)
                    
                    if valid_paragraphs:
                        content = '\n\n'.join(valid_paragraphs)
                        print(f"Content found using improved paragraphs (length: {len(content)})")
            
            if not content:
                print(f"No content found for {url}")
                return ""
            
            # Enhanced text cleaning
            clean_content = self.clean_extracted_content(content)
            
            # Return substantial content for AI processing (increased limit)
            final_content = clean_content[:8000] if clean_content else ""
            print(f"Final content length for {url}: {len(final_content)}")
            
            return final_content
            
        except requests.exceptions.RequestException as e:
            print(f"Request error scraping {url}: {e}")
            return ""
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return ""

    def clean_extracted_content(self, content):
        """Enhanced content cleaning"""
        if not content:
            return ""
        
        lines = []
        skip_patterns = [
            'menu', 'search', 'subscribe', 'newsletter', 'follow us', 
            'share', 'tweet', 'facebook', 'linkedin', 'email',
            'advertisement', 'sponsored', 'techcrunch', 'crunchbase',
            'image credit', 'getty images', 'save', 'sign up',
            'build smarter', 'looking back', 'what do you feel', 
            'techcrunch event', 'all stage pass', 'privacy policy',
            'terms of service', 'cookie policy', 'all rights reserved'
        ]
        
        for line in content.splitlines():
            line = line.strip()
            if (len(line) > 25 and 
                not line.isdigit() and 
                '©' not in line and
                not any(pattern in line.lower() for pattern in skip_patterns) and
                not re.match(r'^\d+\s*(comments?|shares?|likes?)', line.lower()) and
                not re.match(r'^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', line.lower())):
                lines.append(line)
        
        return '\n'.join(lines)

    def try_groq_free(self, content, title):
        """Enhanced Groq API with better prompt and formatting"""
        try:
            groq_key = os.getenv('GROQ_API_KEY')
            if not groq_key:
                print("No GROQ API key found")
                return None
            
            if not content or len(content.strip()) < 200:
                print(f"Content too short for GROQ processing: {len(content) if content else 0} characters")
                return None
            
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            }
            
            # Improved system prompt
            system_prompt = """You are a business intelligence analyst specializing in healthcare and technology. Create executive summaries that capture the most important business insights.

FOCUS ON:
- Funding amounts, revenue figures, and financial metrics
- Strategic partnerships and business deals
- Market size, growth rates, and competitive positioning
- Regulatory developments and policy changes
- Technology innovations with business impact

FORMAT REQUIREMENTS:
- Create exactly 3-4 complete bullet points
- Each bullet point should be 25-40 words
- Start with the most important element (company name, dollar amount, or key metric)
- Use complete sentences that flow naturally
- Include specific numbers and percentages when available
- Avoid cutting off mid-sentence

EXAMPLE:
• Sarepta Therapeutics reported $967.1 million in combined revenue from three key products in 2024, representing a 2% increase from the previous year
• Elevidys gene therapy generated $8 million in revenue during 2024, significantly up from $200,000 in the prior year
• The company faces regulatory scrutiny following a patient fatality linked to Elevidys treatment for Duchenne muscular dystrophy"""

            # Strategic content truncation
            content_preview = content[:6000]
            
            payload = {
                "model": "mixtral-8x7b-32768",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user", 
                        "content": f"""Create a 3-4 bullet executive summary for this article. Focus on business metrics, financial data, partnerships, and strategic developments:

TITLE: {title}

CONTENT:
{content_preview}

Provide 3-4 complete bullet points highlighting the key business insights:"""
                    }
                ],
                "max_tokens": 500,
                "temperature": 0.1,
                "top_p": 0.9
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                summary = result['choices'][0]['message']['content']
                print(f"GROQ raw response: {summary}")
                formatted_summary = self.format_ai_summary(summary)
                print(f"GROQ formatted summary: {formatted_summary}")
                return formatted_summary
            else:
                print(f"Groq API Error: {response.status_code} - {response.text}")
            
        except Exception as e:
            print(f"Groq API error: {e}")
        
        return None

    def format_ai_summary(self, summary_text):
        """Improved summary formatting that preserves sentence integrity"""
        if not summary_text:
            return ""
        
        print(f"Formatting summary: {summary_text}")
        
        # Remove common AI response prefixes
        prefixes_to_remove = [
            "Here are the key points:",
            "Here's a summary:",
            "Executive Summary:",
            "Summary:",
            "Key insights:",
            "Here are 3-4 bullet points:",
            "Based on the article:",
            "Here are the key business insights:"
        ]
        
        cleaned_text = summary_text.strip()
        for prefix in prefixes_to_remove:
            if cleaned_text.lower().startswith(prefix.lower()):
                cleaned_text = cleaned_text[len(prefix):].strip()
        
        # Split by lines and process
        lines = [line.strip() for line in cleaned_text.split('\n') if line.strip()]
        bullets = []
        
        for line in lines:
            # Skip empty lines
            if not line:
                continue
            
            # Check if it's already a bullet point
            bullet_patterns = ['•', '-', '*', '▪', '○']
            numbered_patterns = [f"{i}." for i in range(1, 10)]
            
            is_bullet = any(line.startswith(pattern + ' ') for pattern in bullet_patterns)
            is_numbered = any(line.startswith(pattern + ' ') for pattern in numbered_patterns)
            
            if is_bullet or is_numbered:
                # Clean up existing bullet formatting
                clean_line = line
                for pattern in bullet_patterns + numbered_patterns:
                    if clean_line.startswith(pattern + ' '):
                        clean_line = clean_line[len(pattern):].strip()
                        break
                
                # Only include substantial bullet points
                if len(clean_line) > 30 and not clean_line.endswith('...'):
                    bullets.append(f"• {clean_line}")
            elif len(line) > 40 and len(bullets) < 4:
                # If it's a substantial line without bullet formatting, add it as a bullet
                bullets.append(f"• {line}")
        
        # If we still don't have good bullets, try different approach
        if len(bullets) < 2:
            # Look for sentences ending with periods
            sentences = re.split(r'(?<=[.!?])\s+', cleaned_text)
            bullets = []
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) > 30 and len(bullets) < 4:
                    # Remove any existing bullet formatting
                    sentence = re.sub(r'^[•\-*▪○]\s*', '', sentence)
                    sentence = re.sub(r'^\d+\.\s*', '', sentence)
                    bullets.append(f"• {sentence}")
        
        # Final validation - ensure we have complete sentences
        validated_bullets = []
        for bullet in bullets[:4]:
            # Remove the bullet marker for validation
            text = bullet[2:].strip()  # Remove "• "
            
            # Check if it's a complete thought (has at least 5 words and ends properly)
            words = text.split()
            if (len(words) >= 8 and 
                len(text) > 25 and
                not text.endswith('...') and
                not text.endswith(',') and
                not text.startswith('$') and len(text) < 10):  # Avoid lone dollar amounts
                validated_bullets.append(bullet)
        
        result = '\n'.join(validated_bullets)
        print(f"Final validated result: {result}")
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
        if not content or len(content.strip()) < 100:
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
        """Enhanced fallback summary method with better key information extraction"""
        if not content or len(content.split()) < 30:
            return f"• {title}\n• Content extraction failed - manual review needed"
        
        # Extract sentences with important business information
        sentences = re.split(r'(?<=[.!?])\s+', content.replace('\n', ' '))
        key_sentences = []
        
        # Enhanced keyword matching for business content
        important_patterns = [
            r'\$[\d,.]+(million|billion|k\b)',  # Money amounts
            r'\d+(\.\d+)?%',  # Percentages
            r'(raised|funding|revenue|sales|profit|loss|investment).*\$[\d,.]+',
            r'(partnership|acquired|merger|deal|agreement).*with.*',
            r'(launched|announced|released|introduced).*',
            r'(FDA|approval|regulatory|clinical|trial).*',
            r'(growth|increase|decrease|decline).*\d+',
            r'(market|industry|sector).*\$[\d,.]+'
        ]
        
        scored_sentences = []
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 40:
                score = 0
                # Score based on important patterns
                for pattern in important_patterns:
                    if re.search(pattern, sentence, re.IGNORECASE):
                        score += 2
                
                # Additional scoring for business keywords
                business_keywords = ['company', 'business', 'revenue', 'profit', 'market', 'customers', 'users', 'growth', 'strategy']
                for keyword in business_keywords:
                    if keyword.lower() in sentence.lower():
                        score += 1
                
                if score > 0:
                    scored_sentences.append((sentence, score))
        
        # Sort by score and take top sentences
        scored_sentences.sort(key=lambda x: x[1], reverse=True)
        key_sentences = [s[0] for s in scored_sentences[:3]]
        
        # If no scored sentences, use first substantial sentences
        if not key_sentences:
            key_sentences = [s.strip() for s in sentences[:3] if len(s.strip()) > 40]
        
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
            if response.status_code == 200:
                return True
            else:
                print(f"Notion API Error: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"Error adding to Notion: {e}")
            return False
    
    def run_daily_aggregation(self):
        """Main function to run daily article aggregation"""
        print(f"Starting aggregation at {datetime.now()}")
        
        all_articles = []
        
        # Fetch articles from all sources
        for category, urls in self.sources.items():
            print(f"Processing {category} sources...")
            for url in urls:
                print(f"Fetching from: {url}")
                articles = self.fetch_rss_articles(url)
                print(f"Found {len(articles)} recent articles")
                
                for article in articles:
                    article['category'] = category
                    
                    # Get full content and summarize
                    print(f"Processing: {article['title']}")
                    content = self.scrape_article_content(article['url'])
                    if content:
                        article['summary'] = self.generate_summary_free(content, article['title'])
                        all_articles.append(article)
                        print(f"Successfully processed: {article['title']}")
                    else:
                        print(f"Failed to extract content from: {article['url']}")
                    
                    # Rate limiting
                    time.sleep(2)
        
        print(f"Total articles processed: {len(all_articles)}")
        
        # Add to Notion
        successful = 0
        for article in all_articles:
            if self.add_to_notion(article):
                successful += 1
                print(f"Added to Notion: {article['title']}")
            else:
                print(f"Failed to add to Notion: {article['title']}")
            time.sleep(1)  # Rate limiting for Notion API
        
        print(f"Successfully added {successful}/{len(all_articles)} articles to Notion")
        return all_articles

# Usage
if __name__ == "__main__":
    aggregator = ArticleAggregator()
    articles = aggregator.run_daily_aggregation()
