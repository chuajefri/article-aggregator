import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import time
import os
import re
from urllib.parse import urljoin, urlparse
import random
from dateutil import parser as date_parser

class ArticleAggregator:
    def __init__(self):
        # Updated and verified RSS sources
        self.sources = {
            'Tech': [
                'https://techcrunch.com/feed/',
                'https://openai.com/blog/rss.xml',
                'https://www.lennysnewsletter.com/feed',
                'https://feeds.feedburner.com/oreilly/radar/atom',  # Additional tech source
                'https://www.theverge.com/rss/index.xml'
            ],
            'Health': [
                'https://www.medicalnewstoday.com/feeds/news.xml',
                'https://www.mobihealthnews.com/feed',  # Fixed URL (removed trailing slash)
                'https://www.fiercehealthcare.com/rss/xml',  # Fixed URL structure
                'https://medcitynews.com/feed/',
                'https://www.healthcareitnews.com/rss/all-news',  # Additional health IT source
                'https://www.modernhealthcare.com/rss/all'  # Additional healthcare source
            ]
        }
        
        # Get tokens from environment variables (GitHub Secrets)
        self.notion_token = os.getenv('NOTION_TOKEN')
        self.notion_database_id = os.getenv('NOTION_DATABASE_ID')
        self.hf_token = os.getenv('HUGGINGFACE_TOKEN')
        self.groq_api_key = os.getenv('GROQ_API_KEY')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        
        # Enhanced headers with rotation for better scraping success
        self.headers_list = [
            {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0'
            },
            {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/rss+xml, application/xml, text/xml',
                'Accept-Language': 'en-US,en;q=0.8',
                'Cache-Control': 'no-cache'
            },
            {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.5'
            }
        ]
        
    def get_random_headers(self):
        """Get random headers to avoid being blocked"""
        return random.choice(self.headers_list)
        
    def validate_rss_url(self, url):
        """Validate and potentially fix RSS URLs"""
        print(f"Validating RSS URL: {url}")
        
        # Test the URL first
        try:
            headers = self.get_random_headers()
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                # Check if it's actually RSS/XML content
                content_type = response.headers.get('content-type', '').lower()
                if any(xml_type in content_type for xml_type in ['xml', 'rss', 'atom']):
                    print(f"✅ Valid RSS URL: {url}")
                    return url
                else:
                    print(f"⚠️  URL returns content but may not be RSS: {url}")
                    # Try to parse anyway
                    feed = feedparser.parse(response.content)
                    if feed.entries:
                        print(f"✅ Content is parseable as RSS: {url}")
                        return url
            else:
                print(f"❌ HTTP {response.status_code} for URL: {url}")
                
        except Exception as e:
            print(f"❌ Error validating URL {url}: {e}")
        
        # Try common variations if original fails
        variations = []
        
        if url.endswith('/feed/'):
            variations.append(url[:-1])  # Remove trailing slash
        elif url.endswith('/feed'):
            variations.append(url + '/')   # Add trailing slash
        
        if 'mobihealthnews.com' in url:
            variations.extend([
                'https://www.mobihealthnews.com/rss',
                'https://www.mobihealthnews.com/feed.xml',
                'https://feeds.feedburner.com/MobiHealthNews'
            ])
        
        if 'fiercehealthcare.com' in url:
            variations.extend([
                'https://www.fiercehealthcare.com/rss.xml',
                'https://www.fiercehealthcare.com/feed',
                'https://www.fiercehealthcare.com/rss/all'
            ])
        
        # Test variations
        for variation in variations:
            try:
                print(f"Trying variation: {variation}")
                headers = self.get_random_headers()
                response = requests.get(variation, headers=headers, timeout=15)
                
                if response.status_code == 200:
                    feed = feedparser.parse(response.content)
                    if feed.entries:
                        print(f"✅ Working variation found: {variation}")
                        return variation
                        
            except Exception as e:
                print(f"Variation failed {variation}: {e}")
                continue
        
        print(f"❌ No working RSS URL found for: {url}")
        return None
        
    def fetch_rss_articles(self, url, hours_back=24):
        """Enhanced RSS fetching with URL validation and better error handling"""
        # First validate the URL
        validated_url = self.validate_rss_url(url)
        if not validated_url:
            print(f"Skipping invalid RSS URL: {url}")
            return []
            
        try:
            print(f"Fetching RSS from validated URL: {validated_url}")
            
            headers = self.get_random_headers()
            response = requests.get(validated_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Check if we got redirected
            if response.url != validated_url:
                print(f"Redirected to: {response.url}")
            
            feed = feedparser.parse(response.content)
            
            # Better feed validation
            if not hasattr(feed, 'entries') or not feed.entries:
                print(f"No entries found in feed: {validated_url}")
                print(f"Feed info: {getattr(feed.feed, 'title', 'No title')}")
                print(f"Bozo: {feed.bozo}")
                if feed.bozo:
                    print(f"Bozo exception: {feed.bozo_exception}")
                return []
                
            recent_articles = []
            cutoff_time = datetime.now() - timedelta(hours=hours_back)
            
            print(f"Feed title: {getattr(feed.feed, 'title', 'Unknown')}")
            print(f"Found {len(feed.entries)} total entries")
            
            for entry in feed.entries:
                try:
                    # Enhanced date parsing with multiple fallback methods
                    pub_date = self.parse_entry_date(entry)
                    
                    # Check if article is recent enough
                    if pub_date and pub_date > cutoff_time:
                        # Get description/summary with better fallbacks
                        description = self.extract_entry_description(entry)
                        
                        article = {
                            'title': self.clean_text(entry.title) if hasattr(entry, 'title') else 'Untitled',
                            'url': entry.link if hasattr(entry, 'link') else '',
                            'published': pub_date.isoformat(),
                            'source': getattr(feed.feed, 'title', 'Unknown Source'),
                            'description': description
                        }
                        
                        # Validate article has required fields
                        if article['url'] and article['title']:
                            recent_articles.append(article)
                            print(f"Added recent article: {article['title'][:80]}...")
                        else:
                            print(f"Skipping article with missing data: {article.get('title', 'No title')}")
                    else:
                        date_str = pub_date.strftime('%Y-%m-%d %H:%M') if pub_date else 'Unknown date'
                        print(f"Article too old: {getattr(entry, 'title', 'No title')[:50]}... ({date_str})")
                        
                except Exception as e:
                    print(f"Error processing entry {getattr(entry, 'title', 'Unknown')}: {e}")
                    continue
            
            print(f"Found {len(recent_articles)} recent articles from {validated_url}")
            return recent_articles
            
        except requests.exceptions.RequestException as e:
            print(f"Request error fetching RSS from {validated_url}: {e}")
            return []
        except Exception as e:
            print(f"Unexpected error fetching RSS from {validated_url}: {e}")
            return []
    
    def parse_entry_date(self, entry):
        """Enhanced date parsing for RSS entries"""
        pub_date = None
        
        # Try multiple date fields and parsing methods
        date_fields = ['published_parsed', 'updated_parsed', 'published', 'updated', 'date']
        
        for field in date_fields:
            try:
                if hasattr(entry, field):
                    field_value = getattr(entry, field)
                    
                    if field_value:
                        # Handle parsed time tuples
                        if field.endswith('_parsed') and isinstance(field_value, (tuple, list)):
                            if len(field_value) >= 6:
                                pub_date = datetime(*field_value[:6])
                                break
                        
                        # Handle string dates
                        elif isinstance(field_value, str):
                            try:
                                pub_date = date_parser.parse(field_value)
                                break
                            except:
                                # Try manual parsing for common formats
                                for fmt in ['%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d %H:%M:%S', '%a, %d %b %Y %H:%M:%S %Z']:
                                    try:
                                        pub_date = datetime.strptime(field_value, fmt)
                                        break
                                    except:
                                        continue
                                if pub_date:
                                    break
                        
            except Exception as e:
                print(f"Error parsing date field {field}: {e}")
                continue
        
        # Default to current time if no date found
        if not pub_date:
            pub_date = datetime.now()
            print(f"Warning: Could not parse date for article, using current time")
        
        return pub_date
    
    def extract_entry_description(self, entry):
        """Extract description from RSS entry with multiple fallbacks"""
        description = ""
        
        # Try different description fields
        desc_fields = ['summary', 'description', 'content', 'subtitle']
        
        for field in desc_fields:
            try:
                if hasattr(entry, field):
                    field_value = getattr(entry, field)
                    
                    if isinstance(field_value, str):
                        description = field_value
                        break
                    elif isinstance(field_value, list) and field_value:
                        # Handle content arrays
                        if isinstance(field_value[0], dict):
                            description = field_value[0].get('value', str(field_value[0]))
                        else:
                            description = str(field_value[0])
                        break
                    elif field_value:
                        description = str(field_value)
                        break
                        
            except Exception as e:
                print(f"Error extracting description from field {field}: {e}")
                continue
        
        # Clean HTML from description
        if description:
            description = BeautifulSoup(description, 'html.parser').get_text()
            description = self.clean_text(description)[:500]  # Limit length
        
        return description
    
    def clean_text(self, text):
        """Clean and normalize text"""
        if not text:
            return ""
        
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text.strip())
        
        # Remove common artifacts
        text = re.sub(r'\[…\]|\[...\]|…', '', text)
        text = re.sub(r'^\s*-\s*', '', text)  # Remove leading dashes
        
        return text
    
    def scrape_article_content(self, url):
        """Enhanced content extraction with improved selectors and error handling"""
        try:
            print(f"Scraping content from: {url}")
            
            # Skip problematic URLs
            if not url or not url.startswith('http'):
                print(f"Invalid URL: {url}")
                return ""
            
            # Add retry logic for failed requests
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    headers = self.get_random_headers()
                    response = requests.get(url, timeout=30, headers=headers)
                    response.raise_for_status()
                    break
                except requests.exceptions.RequestException as e:
                    print(f"Attempt {attempt + 1} failed for {url}: {e}")
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(random.uniform(2, 5))  # Random delay between retries
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Enhanced unwanted elements removal
            unwanted_selectors = [
                'script', 'style', 'nav', 'header', 'footer', 'sidebar', 
                'advertisement', 'ads', '.ad', '.advertisement', '.sidebar',
                '.related-posts', '.comments', '.comment', '.social-share', '.newsletter',
                '.popup', '.modal', '.cookie-notice', '.breadcrumb', '.tags',
                '.author-bio', '.post-meta', '.share-buttons', '[role="complementary"]',
                '.wp-block-group', '.entry-meta', '.post-navigation', '.author-info',
                '.related-content', '.promo', '.callout', '.embed', '.video-player',
                '.toc', '.table-of-contents', '.byline', '.dateline', '.subheading',
                '.wp-block-separator', '.wp-block-spacer', '.social-links',
                '.newsletter-signup', '.cta', '.call-to-action', '.widget',
                '.recommended', '.trending', '.popular', '.most-read',
                '[data-module="Advertisement"]', '.sticky-ad', '.inline-ad',
                '.mobile-ad', '.desktop-ad', '.banner-ad', '.display-ad'
            ]
            
            for selector in unwanted_selectors:
                for element in soup.select(selector):
                    element.decompose()
            
            # Site-specific content selectors (ordered by specificity)
            content_selectors = [
                # TechCrunch specific
                '.wp-block-post-content',
                '.entry-content',
                '.article-content',
                '.post-content',
                '.single-post-content',
                '.article-body',
                '.tc-article-content',
                '.article__content',
                
                # Fierce Healthcare specific
                '.field-name-body',
                '.article-body-content',
                '.node-content',
                '.field-item',
                '.fierce-content',
                
                # Medical News Today specific
                '.css-1p8ayus',
                '.article-body',
                '.content-body',
                
                # MobiHealthNews specific
                '.entry-content',
                '.post-content',
                '.article-content',
                
                # Healthcare IT News specific
                '.node-body',
                '.field-name-body',
                
                # General selectors (ordered by specificity)
                'article .content',
                'article main',
                'article',
                '[role="main"] article',
                '[role="main"]',
                '.main-content',
                '.post-body',
                '.story-body',
                '.content-body',
                'main',
                '.content',
                '.page-content',
                
                # Fallback selectors
                '#content',
                '.single-content',
                '.primary-content'
            ]
            
            content = ""
            used_selector = ""
            
            for selector in content_selectors:
                try:
                    elements = soup.select(selector)
                    if elements:
                        # Get the element with the most text content
                        content_element = max(elements, key=lambda x: len(x.get_text().strip()))
                        raw_content = content_element.get_text()
                        
                        if len(raw_content.strip()) > 200:
                            content = raw_content
                            used_selector = selector
                            print(f"Content found using selector: {selector} (length: {len(content)})")
                            break
                except Exception as e:
                    print(f"Error with selector {selector}: {e}")
                    continue
            
            # Enhanced paragraph fallback
            if not content or len(content.strip()) < 200:
                print("Trying enhanced paragraph extraction...")
                content = self.extract_paragraphs(soup)
            
            # Final fallback: full text extraction with filtering
            if not content or len(content.strip()) < 100:
                print("Trying full text extraction with filtering...")
                all_text = soup.get_text()
                if len(all_text.strip()) > 500:
                    content = self.clean_extracted_content(all_text)
                    print(f"Content found using full text extraction (length: {len(content)})")
            
            if not content or len(content.strip()) < 50:
                print(f"Minimal content found for {url}")
                return ""
            
            # Enhanced text cleaning
            clean_content = self.clean_extracted_content(content)
            
            # Return substantial content for AI processing
            final_content = clean_content[:15000] if clean_content else ""  # Increased limit
            print(f"Final content length for {url}: {len(final_content)}")
            
            return final_content
            
        except requests.exceptions.RequestException as e:
            print(f"Request error scraping {url}: {e}")
            return ""
        except Exception as e:
            print(f"Unexpected error scraping {url}: {e}")
            return ""

    def extract_paragraphs(self, soup):
        """Enhanced paragraph extraction with site-specific improvements"""
        paragraph_strategies = [
            'article p',
            '.post-content p',
            '.entry-content p', 
            '.article-content p',
            '.wp-block-post-content p',
            '.field-name-body p',  # Fierce Healthcare
            '.article-body p',
            '.content-body p',
            'main p',
            '.content p',
            'p'  # Last resort
        ]
        
        for strategy in paragraph_strategies:
            try:
                paragraphs = soup.select(strategy)
                if paragraphs and len(paragraphs) >= 2:  # Need at least 2 paragraphs
                    valid_paragraphs = self.filter_paragraphs(paragraphs)
                    if len(valid_paragraphs) >= 2:
                        content = '\n\n'.join(valid_paragraphs)
                        print(f"Content found using paragraph strategy: {strategy} (length: {len(content)})")
                        return content
            except Exception as e:
                print(f"Error with paragraph strategy {strategy}: {e}")
                continue
        
        return ""

    def filter_paragraphs(self, paragraphs):
        """Enhanced paragraph filtering"""
        valid_paragraphs = []
        
        skip_phrases = [
            'subscribe', 'newsletter', 'follow us', 'share this',
            'read more', 'continue reading', 'advertisement',
            'sponsored', 'getty images', 'image credit',
            'techcrunch', 'crunchbase', 'save', 'menu',
            'build smarter', 'looking back', 'what do you feel',
            'all rights reserved', 'privacy policy', 'terms of service',
            'cookie policy', 'contact us', 'about us', 'related articles',
            'you might also like', 'recommended for you', 'trending now',
            'most popular', 'editor picks', 'latest news', 'sign up',
            'click here', 'learn more', 'find out more'
        ]
        
        for p in paragraphs:
            p_text = p.get_text().strip()
            
            # Enhanced filtering criteria
            if (len(p_text) > 25 and
                len(p_text.split()) > 6 and
                not any(skip in p_text.lower() for skip in skip_phrases) and
                not p_text.lower().startswith(('image:', 'photo:', 'video:', 'advertisement', 'share', 'follow')) and
                not re.match(r'^\d+\s*(min|hour|day|week|month|year)', p_text.lower()) and
                not re.match(r'^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', p_text.lower()) and
                '©' not in p_text and
                not p_text.isdigit() and
                not re.match(r'^[\d\s\-/:.]+$', p_text) and
                not p_text.count('|') > 3):  # Avoid navigation menus
                
                valid_paragraphs.append(p_text)
        
        return valid_paragraphs

    def clean_extracted_content(self, content):
        """Enhanced content cleaning"""
        if not content:
            return ""
        
        # Split into lines and filter
        lines = []
        skip_patterns = [
            'menu', 'search', 'subscribe', 'newsletter', 'follow us', 
            'share', 'tweet', 'facebook', 'linkedin', 'email',
            'advertisement', 'sponsored', 'techcrunch', 'crunchbase',
            'image credit', 'getty images', 'save', 'sign up',
            'build smarter', 'looking back', 'what do you feel', 
            'techcrunch event', 'all stage pass', 'privacy policy',
            'terms of service', 'cookie policy', 'all rights reserved',
            'related articles', 'you might also like', 'recommended',
            'trending', 'most popular', 'latest news', 'editor picks',
            'click here', 'learn more', 'find out more', 'read full'
        ]
        
        for line in content.splitlines():
            line = line.strip()
            if (len(line) > 20 and
                len(line.split()) > 4 and
                not line.isdigit() and 
                '©' not in line and
                not any(pattern in line.lower() for pattern in skip_patterns) and
                not re.match(r'^\d+\s*(comments?|shares?|likes?)', line.lower()) and
                not re.match(r'^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', line.lower()) and
                not re.match(r'^[\d\s\-/:.]+$', line) and
                line.count('|') < 4):  # Avoid navigation
                lines.append(line)
        
        cleaned_content = '\n'.join(lines)
        
        # Remove duplicate lines
        unique_lines = []
        seen_lines = set()
        
        for line in cleaned_content.splitlines():
            line = line.strip()
            if line and line not in seen_lines and len(line) > 15:
                unique_lines.append(line)
                seen_lines.add(line)
        
        return '\n'.join(unique_lines)

    def try_groq_free(self, content, title):
        """Enhanced Groq API with better prompting"""
        try:
            if not self.groq_api_key:
                print("No GROQ API key found")
                return None
            
            if not content or len(content.strip()) < 100:
                print(f"Content too short for GROQ processing: {len(content) if content else 0} characters")
                return None
            
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.groq_api_key}",
                "Content-Type": "application/json"
            }
            
            # Enhanced system prompt
            system_prompt = """You are a business intelligence analyst. Create concise executive summaries that capture key business developments, financial metrics, and strategic implications.

REQUIREMENTS:
- Create exactly 3-4 bullet points
- Each point: 15-40 words
- Start with the most important element (company, amount, development)
- Include specific numbers, percentages, dates when available
- Focus on actionable business intelligence
- Use clear, professional language

FOCUS ON:
- Funding rounds, revenue, financial metrics
- Partnerships, acquisitions, strategic deals
- Product launches, clinical trials, regulatory approvals
- Market trends, competitive positioning
- Leadership changes, company pivots"""

            content_preview = content[:10000]
            
            payload = {
                "model": "mixtral-8x7b-32768",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user", 
                        "content": f"Create 3-4 executive summary points for:\n\nTITLE: {title}\n\nCONTENT:\n{content_preview}"
                    }
                ],
                "max_tokens": 400,
                "temperature": 0.1,
                "top_p": 0.9
            }
            
            # Retry logic
            for attempt in range(2):
                try:
                    response = requests.post(url, headers=headers, json=payload, timeout=60)
                    
                    if response.status_code == 200:
                        result = response.json()
                        summary = result['choices'][0]['message']['content']
                        formatted_summary = self.format_ai_summary(summary)
                        
                        if formatted_summary and len(formatted_summary.strip()) > 50:
                            print(f"✅ GROQ summary generated successfully")
                            return formatted_summary
                    else:
                        print(f"Groq API Error: {response.status_code} - {response.text}")
                        
                except Exception as e:
                    print(f"Groq API request error (attempt {attempt + 1}): {e}")
                    if attempt == 0:
                        time.sleep(3)
            
        except Exception as e:
            print(f"Groq API error: {e}")
        
        return None

    def format_ai_summary(self, summary_text):
        """Improved summary formatting"""
        if not summary_text:
            return ""
        
        # Remove common prefixes
        prefixes_to_remove = [
            "Here are the key points:", "Here's a summary:", "Executive Summary:",
            "Summary:", "Key insights:", "Here are 3-4 bullet points:",
            "Based on the article:", "Here are the key business insights:",
            "Key business developments:", "Main points:", "Important highlights:"
        ]
        
        cleaned_text = summary_text.strip()
        for prefix in prefixes_to_remove:
            if cleaned_text.lower().startswith(prefix.lower()):
                cleaned_text = cleaned_text[len(prefix):].strip()
        
        # Process lines into bullets
        lines = [line.strip() for line in cleaned_text.split('\n') if line.strip()]
        bullets = []
        
        for line in lines:
            if not line:
                continue
            
            # Clean existing bullet formatting
            bullet_patterns = ['•', '-', '*', '▪', '○', '·'] + [f"{i}." for i in range(1, 10)]
            clean_line = line
            
            for pattern in bullet_patterns:
                if clean_line.startswith(pattern + ' '):
                    clean_line = clean_line[len(pattern):].strip()
                    break
            
            # Validate content quality
            words = clean_line.split()
            if (len(words) >= 5 and len(words) <= 50 and
                len(clean_line) > 20 and
                not clean_line.endswith('...') and
                '.' in clean_line and
                len(bullets) < 4):
                bullets.append(f"• {clean_line}")
        
        # If no good bullets found, try sentence splitting
        if len(bullets) < 2:
            sentences = re.split(r'(?<=[.!?])\s+', cleaned_text)
            bullets = []
            for sentence in sentences[:4]:
                sentence = sentence.strip()
                words = sentence.split()
                if (len(words) >= 5 and len(words) <= 50 and
                    len(sentence) > 20 and
                    sentence.endswith(('.', '!', '?'))):
                    bullets.append(f"• {sentence}")
        
        return '\n'.join(bullets[:4])

    def generate_summary_free(self, content, title):
        """Generate summary using free AI service with enhanced fallbacks"""
        print(f"Generating summary for: {title}")
        print(f"Content length: {len(content) if content else 0}")
        
        # Enhanced content validation
        if not content or len(content.strip()) < 50:  # Lowered threshold
            print("Content too short, using enhanced title-based summary")
            return self.create_title_based_summary(title)
        
        try:
            # Try Method 1: Groq (fastest, great free tier)
            summary = self.try_groq_free(content, title)
            if summary and len(summary.strip()) > 30:
                return summary
            
            # Try Method 2: OpenAI Free Tier (if available)
            summary = self.try_openai_free(content, title)
            if summary and len(summary.strip()) > 30:
                return summary
            
            # Try Method 3: Hugging Face Chat Model (if available)
            summary = self.try_hf_chat_model(content, title)
            if summary and len(summary.strip()) > 30:
                return summary
                
        except Exception as e:
            print(f"Error generating AI summary: {e}")
        
        # Fallback: enhanced content-based summary
        return self.enhanced_simple_summary(content, title)

    def create_title_based_summary(self, title):
        """Create a basic summary from title when content extraction fails"""
        # Extract key information from title
        summary_parts = []
        
        # Look for company names (capitalized words)
        companies = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', title)
        if companies:
            summary_parts.append(f"Article focuses on {', '.join(companies[:2])}")
        
        # Look for financial information
        money_matches = re.findall(r'\$[\d,.]+(million|billion|M|B|k)', title, re.IGNORECASE)
        if money_matches:
            summary_parts.append(f"Involves financial amounts: {', '.join(money_matches)}")
        
        # Look for action words
        action_words = ['raises', 'launches', 'announces', 'acquires', 'partners', 'releases', 'expands']
        found_actions = [word for word in action_words if word.lower() in title.lower()]
        if found_actions:
            summary_parts.append(f"Key developments include: {', '.join(found_actions)}")
        
        if summary_parts:
            return f"• {title}\n• " + '\n• '.join(summary_parts)
        else:
            return f"• {title}\n• Content extraction failed - requires manual review for detailed analysis"

    def enhanced_simple_summary(self, content, title):
        """Enhanced fallback summary with better business content extraction"""
        if not content or len(content.split()) < 20:
            return self.create_title_based_summary(title)
        
        # Extract sentences with important business information
        sentences = re.split(r'(?<=[.!?])\s+', content.replace('\n', ' '))
        
        # Enhanced scoring system for business relevance
        scored_sentences = []
        
        # Financial patterns (highest priority)
        financial_patterns = [
            r'\$[\d,.]+(million|billion|k\b)',
            r'\d+(\.\d+)?%',
            r'(raised|funding|revenue|sales|profit|loss|investment|valuation).*\$[\d,.]+',
            r'(round|series [abc]|seed|ipo).*\$[\d,.]+'
        ]
        
        # Business development patterns
        business_patterns = [
            r'(partnership|acquired|merger|deal|agreement|collaboration).*with.*',
            r'(launched|announced|released|introduced|unveiled).*',
            r'(approved|approval|cleared|authorized).*',
            r'(growth|increase|decrease|decline|up|down).*\d+',
            r'(market|industry|sector).*\$[\d,.]+'
        ]
        
        # Company and people patterns
        entity_patterns = [
            r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(Inc|Corp|Ltd|LLC|Technologies|Therapeutics|Pharma)',
            r'CEO|CTO|CFO|founder|president|executive',
            r'FDA|SEC|FTC|CMS|HIPAA'
        ]
        
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 30 and len(sentence.split()) > 6:
                score = 0
                
                # Score financial information (highest weight)
                for pattern in financial_patterns:
                    if re.search(pattern, sentence, re.IGNORECASE):
                        score += 5
                
                # Score business developments
                for pattern in business_patterns:
                    if re.search(pattern, sentence, re.IGNORECASE):
                        score += 3
                
                # Score entities and key people
                for pattern in entity_patterns:
                    if re.search(pattern, sentence, re.IGNORECASE):
                        score += 2
                
                # Score general business keywords
                business_keywords = ['company', 'business', 'customers', 'users', 'platform', 'technology', 'service', 'product']
                for keyword in business_keywords:
                    if keyword.lower() in sentence.lower():
                        score += 1
                
                if score > 0:
                    scored_sentences.append((sentence, score))
        
        # Sort by score and take top sentences
        scored_sentences.sort(key=lambda x: x[1], reverse=True)
        key_sentences = [s[0] for s in scored_sentences[:4]]
        
        # If no scored sentences, use first substantial sentences
        if not key_sentences:
            key_sentences = [s.strip() for s in sentences[:4] if len(s.strip()) > 30]
        
        # Create bullet points
        bullets = []
        for i, sentence in enumerate(key_sentences[:3]):
            if len(sentence.strip()) > 20:
                bullets.append(f"• {sentence.strip()}")
        
        if not bullets:
            return self.create_title_based_summary(title)
        
        return '\n'.join(bullets)
        
    def add_to_notion(self, article):
        """Enhanced Notion integration with better error handling and validation"""
        if not self.notion_token or not self.notion_database_id:
            print("Missing Notion credentials")
            return False
            
        url = f"https://api.notion.com/v1/pages"
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        
        # Validate and clean article data
        title = article.get('title', 'Untitled Article')[:2000]  # Notion title limit
        article_url = article.get('url', '')
        source = article.get('source', 'Unknown Source')[:2000]
        published = article.get('published', datetime.now().isoformat())
        summary = article.get('summary', 'No summary available')[:2000]  # Notion text limit
        category = article.get('category', 'Uncategorized')
        
        # Ensure we have a valid URL
        if not article_url or not article_url.startswith('http'):
            print(f"Invalid URL for article: {title}")
            return False
        
        data = {
            "parent": {"database_id": self.notion_database_id},
            "properties": {
                "Title": {
                    "title": [{"text": {"content": title}}]
                },
                "URL": {
                    "url": article_url
                },
                "Source": {
                    "rich_text": [{"text": {"content": source}}]
                },
                "Published": {
                    "date": {"start": published.split('T')[0]}  # Extract date part only
                },
                "Summary": {
                    "rich_text": [{"text": {"content": summary}}]
                },
                "Category": {
                    "select": {"name": category}
                }
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                print(f"Successfully added to Notion: {title}")
                return True
            else:
                print(f"Notion API Error: {response.status_code}")
                print(f"Response: {response.text}")
                
                # Try to handle common errors
                if response.status_code == 400:
                    error_data = response.json()
                    print(f"Bad request details: {error_data}")
                    
                    # If it's a validation error, try with minimal data
                    if 'validation' in str(error_data).lower():
                        minimal_data = {
                            "parent": {"database_id": self.notion_database_id},
                            "properties": {
                                "Title": {
                                    "title": [{"text": {"content": title[:100]}}]  # Shorter title
                                }
                            }
                        }
                        retry_response = requests.post(url, headers=headers, json=minimal_data, timeout=30)
                        if retry_response.status_code == 200:
                            print(f"Added to Notion with minimal data: {title}")
                            return True
                
                return False
                
        except Exception as e:
            print(f"Error adding to Notion: {e}")
            return False
    
    def run_daily_aggregation(self):
        """Enhanced main aggregation function with better error handling and reporting"""
        print(f"Starting enhanced aggregation at {datetime.now()}")
        print("=" * 60)
        
        # Validate environment variables
        missing_vars = []
        if not self.notion_token:
            missing_vars.append('NOTION_TOKEN')
        if not self.notion_database_id:
            missing_vars.append('NOTION_DATABASE_ID')
        
        if missing_vars:
            print(f"WARNING: Missing environment variables: {', '.join(missing_vars)}")
            print("Articles will be processed but not added to Notion")
        
        all_articles = []
        source_stats = {}
        
        # Process each category
        for category, urls in self.sources.items():
            print(f"\n🔍 Processing {category} sources...")
            print("-" * 40)
            
            category_articles = []
            
            for url in urls:
                try:
                    print(f"\n📡 Fetching from: {url}")
                    articles = self.fetch_rss_articles(url, hours_back=48)  # Extended to 48 hours for better coverage
                    
                    source_name = url.split('/')[2]  # Extract domain
                    source_stats[source_name] = {
                        'fetched': len(articles),
                        'processed': 0,
                        'successful': 0
                    }
                    
                    print(f"Found {len(articles)} recent articles from {source_name}")
                    
                    for i, article in enumerate(articles, 1):
                        print(f"\n📄 Processing article {i}/{len(articles)}: {article['title'][:80]}...")
                        
                        article['category'] = category
                        
                        # Get full content with retries
                        content = self.scrape_article_content(article['url'])
                        source_stats[source_name]['processed'] += 1
                        
                        if content and len(content.strip()) > 50:
                            # Generate summary
                            article['summary'] = self.generate_summary_free(content, article['title'])
                            
                            if article['summary'] and len(article['summary'].strip()) > 30:
                                all_articles.append(article)
                                category_articles.append(article)
                                source_stats[source_name]['successful'] += 1
                                print(f"✅ Successfully processed: {article['title'][:60]}...")
                            else:
                                print(f"⚠️  Summary generation failed for: {article['title'][:60]}...")
                        else:
                            print(f"❌ Content extraction failed for: {article['title'][:60]}...")
                        
                        # Rate limiting with random jitter to avoid being blocked
                        import random
                        delay = random.uniform(1, 3)  # Random delay between 1-3 seconds
                        time.sleep(delay)
                
                except Exception as e:
                    print(f"❌ Error processing source {url}: {e}")
                    continue
            
            print(f"\n📊 {category} Summary: {len(category_articles)} articles successfully processed")
        
        # Print overall statistics
        print(f"\n" + "=" * 60)
        print(f"📈 AGGREGATION SUMMARY")
        print("=" * 60)
        print(f"Total articles processed: {len(all_articles)}")
        print(f"\nSource breakdown:")
        for source, stats in source_stats.items():
            success_rate = (stats['successful'] / stats['fetched'] * 100) if stats['fetched'] > 0 else 0
            print(f"  {source:<25} | Fetched: {stats['fetched']:>2} | Processed: {stats['processed']:>2} | Success: {stats['successful']:>2} ({success_rate:.1f}%)")
        
        # Add to Notion if credentials available
        if self.notion_token and self.notion_database_id and all_articles:
            print(f"\n📝 Adding articles to Notion...")
            print("-" * 40)
            
            successful_notion = 0
            failed_notion = 0
            
            for i, article in enumerate(all_articles, 1):
                try:
                    print(f"Adding {i}/{len(all_articles)}: {article['title'][:50]}...")
                    if self.add_to_notion(article):
                        successful_notion += 1
                    else:
                        failed_notion += 1
                except Exception as e:
                    print(f"Error adding article to Notion: {e}")
                    failed_notion += 1
                
                # Rate limiting for Notion API
                time.sleep(1)
            
            print(f"\n📋 Notion Summary:")
            print(f"  Successfully added: {successful_notion}")
            print(f"  Failed to add: {failed_notion}")
            print(f"  Success rate: {(successful_notion / len(all_articles) * 100):.1f}%")
        
        elif all_articles:
            print(f"\n⚠️  Notion credentials not available - {len(all_articles)} articles processed but not saved")
        
        # Save articles to JSON file as backup
        if all_articles:
            try:
                backup_filename = f"articles_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                with open(backup_filename, 'w', encoding='utf-8') as f:
                    json.dump(all_articles, f, indent=2, ensure_ascii=False, default=str)
                print(f"\n💾 Backup saved to: {backup_filename}")
            except Exception as e:
                print(f"⚠️  Could not save backup file: {e}")
        
        print(f"\n🎉 Aggregation completed at {datetime.now()}")
        print("=" * 60)
        
        return all_articles

# Enhanced usage with better error handling
if __name__ == "__main__":
    try:
        print("🚀 Starting Article Aggregator...")
        aggregator = ArticleAggregator()
        articles = aggregator.run_daily_aggregation()
        
        if articles:
            print(f"\n✨ Successfully completed! Processed {len(articles)} articles.")
        else:
            print(f"\n⚠️  No articles were successfully processed. Check the logs above for issues.")
            
    except KeyboardInterrupt:
        print(f"\n⏹️  Aggregation interrupted by user")
    except Exception as e:
        print(f"\n💥 Fatal error during aggregation: {e}")
        import traceback
        traceback.print_exc()
