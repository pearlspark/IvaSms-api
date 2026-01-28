# Copyright @Arslan-MD
# Updates Channel t.me/arslanmd
from flask import Flask, request, jsonify
from datetime import datetime
import cloudscraper
import json
from bs4 import BeautifulSoup
import logging
import os
import gzip
from io import BytesIO
import brotli

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class IVASSMSClient:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.base_url = "https://www.ivasms.com"
        self.logged_in = False
        self.csrf_token = None
        
        # 设置更真实的请求头
        self.scraper.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        })

    def decompress_response(self, response):
        """Decompress response content if encoded with gzip or brotli."""
        encoding = response.headers.get('Content-Encoding', '').lower()
        content = response.content
        try:
            if encoding == 'gzip':
                logger.debug("Decompressing gzip response")
                content = gzip.decompress(content)
            elif encoding == 'br':
                logger.debug("Decompressing brotli response")
                content = brotli.decompress(content)
            return content.decode('utf-8', errors='replace')
        except Exception as e:
            logger.error(f"Error decompressing response: {e}")
            return response.text

    def load_cookies(self, file_path="cookies.json"):
        try:
            if os.getenv("COOKIES_JSON"):
                cookies_raw = json.loads(os.getenv("COOKIES_JSON"))
                logger.debug("Loaded cookies from environment variable")
            else:
                with open(file_path, 'r') as file:
                    cookies_raw = json.load(file)
                    logger.debug("Loaded cookies from file")
            
            if isinstance(cookies_raw, dict):
                logger.debug("Cookies loaded as dictionary")
                return cookies_raw
            elif isinstance(cookies_raw, list):
                cookies = {}
                for cookie in cookies_raw:
                    if 'name' in cookie and 'value' in cookie:
                        cookies[cookie['name']] = cookie['value']
                logger.debug("Cookies loaded as list")
                return cookies
            else:
                logger.error("Cookies are in an unsupported format")
                raise ValueError("Cookies are in an unsupported format.")
        except FileNotFoundError:
            logger.error("cookies.json file not found")
            return None
        except json.JSONDecodeError:
            logger.error("Invalid JSON format in cookies.json")
            return None
        except Exception as e:
            logger.error(f"Error loading cookies: {e}")
            return None

    def save_cookies(self):
        """保存当前 Cookie 到文件"""
        try:
            cookies_dict = {}
            for cookie in self.scraper.cookies:
                cookies_dict[cookie.name] = cookie.value
            
            with open("cookies.json", "w") as f:
                json.dump(cookies_dict, f, indent=2)
            logger.info("Cookies saved successfully")
        except Exception as e:
            logger.error(f"Error saving cookies: {e}")

    def direct_login(self, email, password):
        """直接使用用户名密码登录"""
        try:
            logger.info(f"Attempting direct login for {email}")
            
            # 首先获取登录页面获取 CSRF token
            response = self.scraper.get(f"{self.base_url}/login", timeout=30)
            if response.status_code != 200:
                logger.error(f"Failed to get login page: {response.status_code}")
                return False
            
            soup = BeautifulSoup(response.text, 'html.parser')
            csrf_input = soup.find('input', {'name': '_token'})
            if not csrf_input:
                logger.error("Could not find CSRF token on login page")
                return False
                
            csrf_token = csrf_input.get('value')
            logger.debug(f"Got CSRF token for login: {csrf_token}")
            
            # 准备登录数据
            payload = {
                '_token': csrf_token,
                'email': email,
                'password': password,
                'remember': 'on'
            }
            
            # 发送登录请求
            login_response = self.scraper.post(
                f"{self.base_url}/login",
                data=payload,
                allow_redirects=True,
                timeout=30
            )
            
            # 验证是否登录成功
            if login_response.status_code == 200:
                # 检查重定向到仪表板
                if "dashboard" in login_response.url or "portal" in login_response.url:
                    self.logged_in = True
                    
                    # 获取新的 CSRF token
                    dashboard_response = self.scraper.get(f"{self.base_url}/portal/sms/received", timeout=30)
                    if dashboard_response.status_code == 200:
                        soup = BeautifulSoup(dashboard_response.text, 'html.parser')
                        new_csrf = soup.find('input', {'name': '_token'})
                        if new_csrf:
                            self.csrf_token = new_csrf.get('value')
                            logger.info(f"Direct login successful. New CSRF: {self.csrf_token}")
                            
                            # 保存 Cookie
                            self.save_cookies()
                            return True
            
            logger.error(f"Direct login failed. Status: {login_response.status_code}, URL: {login_response.url}")
            return False
            
        except Exception as e:
            logger.error(f"Direct login error: {e}")
            return False

    def login_with_cookies(self, cookies_file="cookies.json"):
        logger.debug("Attempting to login with cookies")
        cookies = self.load_cookies(cookies_file)
        if not cookies:
            logger.error("No valid cookies loaded")
            return False
        
        # 清除现有 cookies 并设置新的
        self.scraper.cookies.clear()
        for name, value in cookies.items():
            self.scraper.cookies.set(name, value, domain=".ivasms.com")
        
        try:
            response = self.scraper.get(f"{self.base_url}/portal/sms/received", timeout=30)
            logger.debug(f"Cookie login response status: {response.status_code}")
            
            if response.status_code == 200:
                html_content = self.decompress_response(response)
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # 检查是否真的登录成功（寻找登出链接或特定元素）
                logout_link = soup.find('a', href=lambda x: x and 'logout' in x) if soup else None
                csrf_input = soup.find('input', {'name': '_token'}) if soup else None
                
                if csrf_input or logout_link:
                    if csrf_input:
                        self.csrf_token = csrf_input.get('value')
                    self.logged_in = True
                    logger.info(f"Logged in successfully with cookies. CSRF: {self.csrf_token}")
                    return True
                else:
                    logger.warning("Cookie may be expired - no CSRF token or logout link found")
                    return False
            
            logger.warning(f"Cookie login failed with status: {response.status_code}")
            return False
            
        except Exception as e:
            logger.error(f"Cookie login error: {e}")
            return False

    # ... 保持其他方法不变 ...

app = Flask(__name__)
client = IVASSMSClient()

def initialize_client():
    """初始化客户端，尝试多种登录方式"""
    # 先尝试 Cookie 登录
    if client.login_with_cookies():
        logger.info("Successfully logged in with cookies")
        return True
    
    # Cookie 失败则尝试直接登录
    logger.info("Cookie login failed, trying direct login...")
    email = os.getenv("IVAS_EMAIL", "riteshmahato2580@gmail.com")
    password = os.getenv("IVAS_PASSWORD", "Sur@2006")
    
    if client.direct_login(email, password):
        logger.info("Successfully logged in with credentials")
        return True
    
    logger.error("All login attempts failed")
    return False

# 在应用启动时初始化
with app.app_context():
    if not initialize_client():
        logger.warning("Initial login failed, will retry on first request")

@app.before_request
def before_request():
    """在每个请求前检查认证状态"""
    if not client.logged_in:
        logger.info("Client not authenticated, attempting to re-login...")
        if not initialize_client():
            logger.error("Failed to re-authenticate")

# ... 保持其他路由和主程序不变 ...
