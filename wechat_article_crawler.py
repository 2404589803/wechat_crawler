import requests
from bs4 import BeautifulSoup
import re
import json
import time
import argparse
import html
import os
import urllib.parse
from urllib.request import urlretrieve
import random
import logging
from config import config

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WeChatArticleCrawler:
    def __init__(self, proxy=None, timeout=10, retry_times=3, retry_delay=2):
        """初始化爬虫
        
        Args:
            proxy (str, optional): 代理服务器地址，格式如 http://127.0.0.1:7890。默认为None不使用代理。
            timeout (int, optional): 请求超时时间，单位秒。默认为10。
            retry_times (int, optional): 请求失败重试次数。默认为3。
            retry_delay (int, optional): 重试延迟时间，单位秒。默认为2。
        """
        self.headers = {
            "User-Agent": config.get("user_agent"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
        }
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.timeout = timeout
        self.retry_times = retry_times
        self.retry_delay = retry_delay
        
        logger.info(f"爬虫初始化完成 [代理: {proxy if proxy else '无'}, 超时: {timeout}秒, 重试: {retry_times}次]")
    
    def _request(self, url, method="get", **kwargs):
        """发送HTTP请求，带有重试机制
        
        Args:
            url (str): 请求的URL
            method (str, optional): 请求方法，支持get和post。默认为"get"。
            **kwargs: 传递给requests的其他参数
        
        Returns:
            Response: requests的Response对象，如果所有重试都失败则返回None
        """
        if "headers" not in kwargs:
            kwargs["headers"] = self.headers
        if "proxies" not in kwargs and self.proxies:
            kwargs["proxies"] = self.proxies
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.timeout
            
        # 合并默认的随机User-Agent
        current_headers = kwargs.get("headers", {})
        kwargs["headers"] = {**self.headers, **current_headers}
        
        # 初始化重试次数
        retry_count = 0
        
        while retry_count <= self.retry_times:
            try:
                if method.lower() == "get":
                    response = requests.get(url, **kwargs)
                elif method.lower() == "post":
                    response = requests.post(url, **kwargs)
                else:
                    raise ValueError(f"不支持的请求方法: {method}")
                
                # 检查响应状态
                if response.status_code == 200:
                    return response
                else:
                    logger.warning(f"请求失败 [URL: {url}, 状态码: {response.status_code}]")
            except Exception as e:
                logger.warning(f"请求异常 [URL: {url}, 错误: {str(e)}]")
            
            # 如果请求失败且未达到最大重试次数，则等待后重试
            retry_count += 1
            if retry_count <= self.retry_times:
                # 使用指数退避策略，延迟时间逐渐增加
                delay = self.retry_delay * (2 ** (retry_count - 1)) + random.uniform(0, 1)
                logger.info(f"等待 {delay:.2f} 秒后进行第 {retry_count} 次重试...")
                time.sleep(delay)
            else:
                logger.error(f"达到最大重试次数 {self.retry_times}，请求失败 [URL: {url}]")
                return None
                
    def download_media(self, url, save_folder, prefix, index, media_type='img'):
        """下载媒体文件（图片或视频）并返回本地路径"""
        if not url or url.startswith('data:'):
            return None
        
        # 确保文件夹存在
        os.makedirs(save_folder, exist_ok=True)
        
        # 获取文件扩展名
        if media_type == 'img':
            # 对于图片，从URL获取扩展名或默认为.jpg
            ext = os.path.splitext(url.split('?')[0])[1]
            if not ext or len(ext) > 5:  # 如果扩展名不存在或异常长度，使用默认值
                ext = '.jpg'
        else:  # 视频
            ext = '.mp4'  # 默认视频扩展名
        
        # 构建保存路径
        filename = f"{prefix}_{media_type}_{index}{ext}"
        save_path = os.path.join(save_folder, filename)
        
        try:
            # 下载文件
            logger.info(f"正在下载{media_type}: {url}")
            response = self._request(url, stream=True)
            
            if response and response.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                logger.info(f"下载成功: {save_path}")
                return save_path
            else:
                logger.warning(f"下载失败，无法获取内容 [URL: {url}]")
                return None
        except Exception as e:
            logger.error(f"下载{media_type}时出错: {e}")
            return None
    
    def extract_video_info(self, iframe_data, soup):
        """从iframe数据中提取视频信息"""
        video_info = {}
        
        # 尝试提取视频源
        video_url = None
        vid = None
        
        # 处理腾讯视频
        vid_match = re.search(r'vid=([^&]+)', iframe_data)
        if vid_match:
            vid = vid_match.group(1)
            # 修改构建腾讯视频链接的方式，使用更可靠的格式
            video_url = f"https://v.qq.com/txp/iframe/player.html?vid={vid}"
            video_info = {
                'type': 'tencent',
                'original_url': video_url,
                'vid': vid,
                'iframe_data': iframe_data
            }
        
        # 检查是否包含完整URL（常见于视频号）
        url_match = re.search(r'(https?://[^\s"\'>]+)', iframe_data)
        if url_match and not video_url:
            found_url = url_match.group(1)
            # 检查是否是视频链接
            if 'v.qq.com' in found_url or 'video' in found_url or '.mp4' in found_url:
                video_url = found_url
                video_info = {
                    'type': 'embedded_url',
                    'original_url': video_url,
                    'iframe_data': iframe_data
                }
        
        # 处理直接包含视频源的情况
        src_match = re.search(r'src=[\'"]([^\'"]+)[\'"]', iframe_data)
        if src_match and not video_url:
            src = src_match.group(1)
            if src.endswith('.mp4') or 'video' in src:
                video_url = src
                video_info = {
                    'type': 'direct',
                    'original_url': video_url,
                    'iframe_data': iframe_data
                }
            elif 'v.qq.com' in src:
                # 如果是腾讯视频的嵌入链接
                video_url = src
                # 检查是否有vid参数
                vid_in_src = re.search(r'vid=([^&]+)', src)
                if vid_in_src:
                    video_info = {
                        'type': 'tencent',
                        'original_url': video_url,
                        'vid': vid_in_src.group(1),
                        'iframe_data': iframe_data
                    }
                else:
                    video_info = {
                        'type': 'tencent_embed',
                        'original_url': video_url,
                        'iframe_data': iframe_data
                    }
        
        # 如果发现了视频信息但链接可能存在问题，确保提供备选链接
        if video_info and video_info.get('type') == 'tencent' and 'vid' in video_info:
            # 提供多个可能的链接格式
            video_info['alternate_urls'] = [
                f"https://v.qq.com/txp/iframe/player.html?vid={video_info['vid']}",  # iframe嵌入播放器
                f"https://v.qq.com/x/page/{video_info['vid']}.html",                # 常规页面
                f"https://v.qq.com/x/cover/mzc002007knwk8q/{video_info['vid']}.html" # 带封面ID的格式
            ]
        
        return video_info
    
    def get_article_info(self, url, download_media=False, media_folder='media', download_videos=False):
        """
        获取微信文章信息（标题、作者、发布时间、正文）
        
        Args:
            url (str): 微信文章URL
            download_media (bool, optional): 是否下载媒体文件（图片和视频）。默认为False。
            media_folder (str, optional): 媒体文件保存文件夹。默认为'media'。
            download_videos (bool, optional): 是否尝试下载视频文件（需要安装yt-dlp）。默认为False。
            
        Returns:
            dict or None: 文章信息字典，如果失败则返回None
        """
        try:
            # 请求文章页面
            logger.info(f"正在请求文章：{url}")
            response = self._request(url)
            
            if not response:
                logger.error(f"无法获取文章内容 [URL: {url}]")
                return None
                
            # 确保使用正确的编码
            if response.encoding.lower() != 'utf-8':
                response.encoding = 'utf-8'
                
            # 解析页面内容
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 提取文章标题
            title = soup.select_one("#activity-name")
            title_text = title.text.strip() if title else "未找到标题"
            
            # 检查是否找到内容，如果标题为"未找到标题"，可能是文章已被删除或者访问受限
            if title_text == "未找到标题":
                # 尝试查找其他可能的错误信息
                error_msg = soup.select_one(".weui-msg__title") or soup.select_one(".tips")
                if error_msg:
                    error_text = error_msg.text.strip()
                    logger.error(f"文章访问受限: {error_text}")
                    return {
                        "error": True,
                        "message": error_text,
                        "original_url": url
                    }
            
            # 提取文章作者
            author = soup.select_one("#js_name") or soup.select_one(".wx_article_info .wx_article_info_one span:first-child")
            author_text = author.text.strip() if author else "未找到作者"
            
            # 提取发布时间
            publish_time = soup.select_one("#publish_time") or soup.select_one("#js_publish_time") or soup.select_one(".wx_article_info_one span.time")
            publish_time_text = publish_time.text.strip() if publish_time else "未找到发布时间"
            
            # 创建用于存储媒体文件的字典
            media_files = {
                'images': [],
                'videos': []
            }
            
            # 创建用于文章标识的安全文件名前缀
            safe_prefix = re.sub(r'[^\w\s-]', '', title_text).replace(' ', '_')
            if len(safe_prefix) > 50:
                safe_prefix = safe_prefix[:50]
            
            # 提取文章内容
            content_div = soup.select_one("#js_content")
            if not content_div:
                logger.warning("未找到文章内容区域，尝试其他选择器")
                content_div = soup.select_one(".rich_media_content") or soup.select_one(".wx_article_content")
                
            if content_div:
                # 处理所有图片
                img_index = 1
                for img in content_div.find_all("img"):
                    # 获取图片URL
                    img_url = None
                    if img.get("data-src"):
                        img_url = img["data-src"]
                        img["src"] = img_url  # 更新src属性
                    elif img.get("src"):
                        img_url = img["src"]
                    
                    # 如果需要下载图片
                    if download_media and img_url:
                        local_path = self.download_media(
                            img_url, 
                            media_folder, 
                            safe_prefix, 
                            img_index,
                            'img'
                        )
                        if local_path:
                            # 将本地路径添加到图片列表
                            media_files['images'].append({
                                'original_url': img_url,
                                'local_path': local_path
                            })
                            # 修改HTML中的图片路径（相对路径）
                            img["src"] = os.path.relpath(local_path, '.').replace('\\', '/')
                            img_index += 1
                
                # 处理所有视频
                video_index = 1
                # 删除音频元素，因为难以提取
                for mpvoice in content_div.find_all("mpvoice"):
                    mpvoice.extract()  
                
                # 查找视频元素 - 处理多种可能的视频容器
                video_elements = []
                # 1. 常规视频iframe视频
                video_elements.extend(content_div.find_all("div", class_=lambda c: c and "video_iframe" in c))
                # 2. iframe标签
                video_elements.extend(content_div.find_all("iframe"))
                # 3. video标签
                video_elements.extend(content_div.find_all("video"))
                # 4. 包含wxv-video类的div
                video_elements.extend(content_div.find_all("div", class_=lambda c: c and "wxv-video" in c))
                # 5. 微信视频号的特殊容器
                video_elements.extend(content_div.find_all("div", class_=lambda c: c and "js_editor_wxvideo" in c))
                # 6. 新增：处理js_video_page_wrap类
                video_elements.extend(content_div.find_all("div", class_=lambda c: c and "js_video_page_wrap" in c))
                
                logger.info(f"找到 {len(video_elements)} 个视频元素")
                
                for video_div in video_elements:
                    # 尝试获取视频URL
                    iframe_data = video_div.get("data-src") or video_div.get("src") or str(video_div)
                    
                    # 提取视频元素
                    if iframe_data:
                        # 提取视频信息
                        video_info = self.extract_video_info(iframe_data, soup)
                        
                        if video_info:
                            # 如果需要下载视频
                            local_video_path = None
                            if download_media and download_videos:
                                local_video_path = self.download_video(
                                    video_info,
                                    media_folder,
                                    safe_prefix,
                                    video_index
                                )
                                if local_video_path:
                                    video_info['local_path'] = local_video_path
                            
                            # 收集视频信息
                            media_files['videos'].append(video_info)
                            
                            # 替换为更明显的视频播放提示
                            new_tag = soup.new_tag("div")
                            new_tag["style"] = "padding:10px; border:1px solid #ddd; background-color:#f9f9f9; margin:10px 0; text-align:center;"
                            
                            # 如果成功下载视频，添加视频标签
                            if local_video_path:
                                video_tag = soup.new_tag("video")
                                video_tag["controls"] = ""
                                video_tag["width"] = "100%"
                                video_tag["style"] = "max-width:600px;"
                                
                                source_tag = soup.new_tag("source")
                                source_tag["src"] = os.path.relpath(local_video_path, '.').replace('\\', '/')
                                source_tag["type"] = "video/mp4"
                                
                                video_tag.append(source_tag)
                                new_tag.append(video_tag)
                                
                                video_link = soup.new_tag("p")
                                video_link.string = "[已下载视频]"
                                new_tag.append(video_link)
                            elif video_info.get('type') == 'tencent':
                                video_link = soup.new_tag("a")
                                video_link["href"] = video_info['original_url']
                                video_link["target"] = "_blank"
                                video_link.string = f"[腾讯视频: {video_info['vid']}]"
                                new_tag.append(video_link)
                                
                                # 如果有备选链接，添加提示
                                if 'alternate_urls' in video_info:
                                    new_tag.append(soup.new_tag("br"))
                                    alt_text = soup.new_tag("small")
                                    alt_text.string = "若链接无效，请尝试："
                                    new_tag.append(alt_text)
                                    
                                    for i, alt_url in enumerate(video_info['alternate_urls']):
                                        if i > 0:  # 跳过第一个，因为和原始链接相同
                                            new_tag.append(soup.new_tag("br"))
                                            alt_link = soup.new_tag("a")
                                            alt_link["href"] = alt_url
                                            alt_link["target"] = "_blank"
                                            alt_link.string = f"备选链接 {i}"
                                            new_tag.append(alt_link)
                            else:
                                # 其他类型视频
                                if 'original_url' in video_info and video_info['original_url'].startswith('http'):
                                    video_link = soup.new_tag("a")
                                    video_link["href"] = video_info['original_url']
                                    video_link["target"] = "_blank"
                                    video_link.string = f"[视频链接: {video_info.get('type', '未知类型')}]"
                                    new_tag.append(video_link)
                                else:
                                    video_text = soup.new_tag("p")
                                    video_text.string = f"[视频内容: {video_info.get('type', '未知类型')}]"
                                    new_tag.append(video_text)
                            
                            video_div.replace_with(new_tag)
                            video_index += 1
                
                # 获取文本内容 - 清理格式
                content_text = content_div.get_text(separator="\n", strip=True)
                
                # 清理HTML内容 - 去除多余属性，只保留基本结构
                for tag in content_div.find_all(True):
                    attrs = dict(tag.attrs)
                    for attr in attrs:
                        if attr not in ['src', 'href', 'alt', 'width', 'height', 'style', 'target']:
                            del tag[attr]
                
                # 获取HTML内容
                content_html = str(content_div)
            else:
                content_text = "未找到文章内容"
                content_html = ""
            
            # 提取永久链接参数（如果有）
            permanent_url = None
            biz_match = re.search(r'__biz=([^&]+)', response.url)
            mid_match = re.search(r'mid=([^&]+)', response.url)
            idx_match = re.search(r'idx=([^&]+)', response.url)
            sn_match = re.search(r'sn=([^&]+)', response.url)
            
            if biz_match and mid_match and idx_match and sn_match:
                biz = biz_match.group(1)
                mid = mid_match.group(1)
                idx = idx_match.group(1)
                sn = sn_match.group(1)
                permanent_url = f"https://mp.weixin.qq.com/s?__biz={biz}&mid={mid}&idx={idx}&sn={sn}"
            
            # 返回结果
            result = {
                "original_url": url,
                "permanent_url": permanent_url if permanent_url else url,
                "title": title_text,
                "author": author_text,
                "publish_time": publish_time_text,
                "content_text": content_text[:500] + "..." if len(content_text) > 500 else content_text,  # 限制输出长度
                "full_content_text": content_text,
                "content_html": content_html,
                "media_files": media_files
            }
            
            return result
            
        except Exception as e:
            print(f"处理URL时出错: {e}")
            return None

    def download_video(self, video_info, save_folder, prefix, index):
        """尝试下载视频到本地"""
        if not video_info or 'original_url' not in video_info:
            return None

        # 确保文件夹存在
        os.makedirs(save_folder, exist_ok=True)
        
        # 构建保存路径
        filename = f"{prefix}_video_{index}.mp4"
        save_path = os.path.join(save_folder, filename)
        
        try:
            # 根据视频类型选择下载方法
            if video_info.get('type') == 'direct' and video_info['original_url'].endswith('.mp4'):
                # 直接MP4链接，可以直接下载
                print(f"正在下载视频: {video_info['original_url']}")
                return self.download_media(video_info['original_url'], save_folder, prefix, index, 'video')
            
            elif 'v.qq.com' in video_info.get('original_url', '') and 'vid' in video_info:
                # 腾讯视频需要特殊处理
                vid = video_info['vid']
                print(f"尝试从腾讯视频下载(VID: {vid})")
                
                # 尝试构造直接访问的URL进行下载
                # 这些大多数情况下不会成功，但某些情况可能有效
                urls_to_try = [
                    f"https://ugcws.video.gtimg.com/uwMROfz2r5zAoaQXGdGnC2dfJ7wFjpl1CyOdV6vIfCTkm6VC/{vid}.mp4",
                    f"https://defaultts.tc.qq.com/{vid}.mp4",
                    f"https://apd-vlive.apdcdn.tc.qq.com/vmipfsgateway.tc.qq.com/{vid}.mp4"
                ]
                
                for url in urls_to_try:
                    try:
                        print(f"尝试从 {url} 下载")
                        response = requests.head(url, headers=self.headers, timeout=5)
                        if response.status_code == 200:
                            return self.download_media(url, save_folder, prefix, index, 'video')
                    except Exception as e:
                        print(f"尝试URL失败: {e}")
                
                # 如果上述方法都失败，尝试使用youtube-dl或其他工具下载
                try:
                    import yt_dlp
                    
                    print("使用yt-dlp尝试下载视频...")
                    for url in video_info.get('alternate_urls', []):
                        try:
                            ydl_opts = {
                                'format': 'mp4',
                                'outtmpl': save_path,
                                'quiet': True,
                                'no_warnings': True
                            }
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                ydl.download([url])
                            
                            if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                                print(f"使用yt-dlp成功下载视频到: {save_path}")
                                return save_path
                        except Exception as e:
                            print(f"yt-dlp下载失败: {e}")
                except ImportError:
                    print("未安装yt-dlp，无法下载腾讯视频。请安装: pip install yt-dlp")
            
            # 其他类型视频的下载逻辑
            elif video_info.get('type') == 'embedded_url':
                # 尝试嵌入URL
                return self.download_media(video_info['original_url'], save_folder, prefix, index, 'video')
                
            print(f"无法下载视频: {video_info.get('original_url')}")
            return None
        except Exception as e:
            print(f"下载视频时出错: {e}")
            return None

    def export_to_markdown(self, result, output_path):
        """将文章内容导出为Markdown格式
        
        Args:
            result (dict): 文章信息字典
            output_path (str): 输出文件路径
            
        Returns:
            bool: 是否成功导出
        """
        try:
            if not result or "title" not in result:
                logger.error("无法导出为Markdown：无效的文章数据")
                return False
                
            # 获取相对路径的媒体文件夹，用于图片链接
            media_folder_rel = os.path.relpath(
                os.path.dirname(output_path),
                '.'
            ).replace('\\', '/')
                
            with open(output_path, 'w', encoding='utf-8') as f:
                # 写入标题
                f.write(f"# {result['title']}\n\n")
                
                # 写入元数据
                f.write(f"> **作者:** {result['author']}  \n")
                f.write(f"> **发布时间:** {result['publish_time']}  \n")
                f.write(f"> **原文链接:** [{result['permanent_url']}]({result['permanent_url']})  \n\n")
                
                # 写入视频信息（如果有）
                if result['media_files']['videos']:
                    f.write("## 视频链接\n\n")
                    for i, video in enumerate(result['media_files']['videos']):
                        f.write(f"### 视频 {i+1}\n")
                        
                        # 如果视频已下载
                        if 'local_path' in video:
                            # 获取相对路径
                            rel_path = os.path.relpath(video['local_path'], os.path.dirname(output_path)).replace('\\', '/')
                            f.write(f"- 本地视频: [{os.path.basename(video['local_path'])}]({rel_path})\n")
                            f.write(f"- 播放命令: `<video controls><source src=\"{rel_path}\" type=\"video/mp4\"></video>`\n")
                        
                        # 否则提供原始链接
                        if 'original_url' in video:
                            f.write(f"- 原始链接: [{video['original_url']}]({video['original_url']})\n")
                            
                        # 如果有备选链接
                        if 'alternate_urls' in video and len(video['alternate_urls']) > 1:
                            f.write("- 备选链接:\n")
                            for j, alt_url in enumerate(video['alternate_urls']):
                                if j > 0:  # 跳过第一个
                                    f.write(f"  - [{alt_url}]({alt_url})\n")
                        
                        f.write("\n")
                    
                    f.write("---\n\n")
                
                # 处理正文内容 - 转换HTML为Markdown
                content_html = result.get('content_html', '')
                if content_html:
                    # 从BeautifulSoup对象创建
                    soup = BeautifulSoup(content_html, 'html.parser')
                    
                    # 处理图片 - 确保使用正确的相对路径
                    for i, img in enumerate(soup.find_all('img')):
                        img_src = img.get('src', '')
                        img_alt = img.get('alt', f'图片{i+1}')
                        
                        # 检查图片是否已下载（是否为相对路径）
                        if img_src and not img_src.startswith(('http://', 'https://', 'data:')):
                            img_md = f"![{img_alt}]({img_src})"
                        elif img_src:
                            img_md = f"![{img_alt}]({img_src})"
                        else:
                            img_md = f"![图片{i+1}](图片链接不可用)"
                            
                        # 替换img标签为Markdown格式
                        img.replace_with(BeautifulSoup(img_md, 'html.parser'))
                    
                    # 处理标题
                    for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                        level = int(h.name[1])
                        h_text = h.get_text().strip()
                        h.replace_with(BeautifulSoup(f"{'#' * level} {h_text}\n\n", 'html.parser'))
                    
                    # 处理段落
                    for p in soup.find_all('p'):
                        p_text = p.get_text().strip()
                        if p_text:
                            p.replace_with(BeautifulSoup(f"{p_text}\n\n", 'html.parser'))
                    
                    # 处理列表
                    for ul in soup.find_all('ul'):
                        items = []
                        for li in ul.find_all('li'):
                            items.append(f"- {li.get_text().strip()}")
                        ul.replace_with(BeautifulSoup("\n".join(items) + "\n\n", 'html.parser'))
                    
                    for ol in soup.find_all('ol'):
                        items = []
                        for i, li in enumerate(ol.find_all('li')):
                            items.append(f"{i+1}. {li.get_text().strip()}")
                        ol.replace_with(BeautifulSoup("\n".join(items) + "\n\n", 'html.parser'))
                    
                    # 处理链接
                    for a in soup.find_all('a'):
                        href = a.get('href', '')
                        text = a.get_text().strip() or href
                        a.replace_with(BeautifulSoup(f"[{text}]({href})", 'html.parser'))
                    
                    # 处理粗体和斜体
                    for strong in soup.find_all(['strong', 'b']):
                        text = strong.get_text().strip()
                        strong.replace_with(BeautifulSoup(f"**{text}**", 'html.parser'))
                    
                    for em in soup.find_all(['em', 'i']):
                        text = em.get_text().strip()
                        em.replace_with(BeautifulSoup(f"*{text}*", 'html.parser'))
                    
                    # 处理引用
                    for blockquote in soup.find_all('blockquote'):
                        lines = blockquote.get_text().strip().split('\n')
                        quote_text = '\n'.join([f"> {line}" for line in lines])
                        blockquote.replace_with(BeautifulSoup(quote_text + "\n\n", 'html.parser'))
                    
                    # 处理分割线
                    for hr in soup.find_all('hr'):
                        hr.replace_with(BeautifulSoup("\n---\n\n", 'html.parser'))
                    
                    # 获取转换后的文本
                    markdown_content = soup.get_text()
                    
                    # 清理多余的空行
                    markdown_content = re.sub(r'\n{3,}', '\n\n', markdown_content)
                    
                    # 写入正文
                    f.write("## 正文\n\n")
                    f.write(markdown_content)
                else:
                    # 如果没有HTML内容，直接使用纯文本
                    f.write("## 正文\n\n")
                    f.write(result.get('full_content_text', '未找到文章内容'))
                
                # 添加图片信息
                if result['media_files']['images']:
                    f.write("\n\n## 图片信息\n\n")
                    f.write(f"文章共包含 {len(result['media_files']['images'])} 张图片\n\n")
                
                logger.info(f"成功导出为Markdown: {output_path}")
                return True
                
        except Exception as e:
            logger.error(f"导出Markdown时出错: {e}")
            return False

    def batch_process(self, urls, output_dir="outputs", formats=None, download_media=False, download_videos=False):
        """批量处理多个微信文章URL
        
        Args:
            urls (list): 微信文章URL列表
            output_dir (str, optional): 输出目录。默认为"outputs"。
            formats (list, optional): 输出格式列表，可选值为"text", "html", "json", "markdown"。默认为["json"]。
            download_media (bool, optional): 是否下载媒体文件。默认为False。
            download_videos (bool, optional): 是否下载视频。默认为False。
            
        Returns:
            dict: 处理结果统计
        """
        if not urls:
            logger.error("URL列表为空，无法进行批量处理")
            return {"success": 0, "failed": 0, "total": 0, "results": []}
            
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        
        # 设置默认格式
        if not formats:
            formats = ["json"]
            
        # 转换中文格式名称
        format_mapping = {
            "文本": "text",
            "HTML": "html",
            "JSON": "json",
            "Markdown": "markdown",
            "markdown": "markdown",
            "html": "html",
            "text": "text",
            "json": "json"
        }
        
        formats = [format_mapping.get(f, f) for f in formats]
        
        # 生成时间戳和子文件夹
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        batch_folder = os.path.join(output_dir, f"batch_{timestamp}")
        os.makedirs(batch_folder, exist_ok=True)
        
        # 准备媒体文件夹
        media_folder = os.path.join(batch_folder, "media")
        if download_media:
            os.makedirs(media_folder, exist_ok=True)
            
        # 统计结果
        results = []
        success_count = 0
        failed_count = 0
        
        # 创建批处理记录文件
        batch_log = os.path.join(batch_folder, "batch_summary.md")
        with open(batch_log, 'w', encoding='utf-8') as log:
            log.write(f"# 微信文章批量爬取结果\n\n")
            log.write(f"- 爬取时间: {timestamp}\n")
            log.write(f"- 文章数量: {len(urls)}\n")
            log.write(f"- 输出格式: {', '.join(formats)}\n")
            log.write(f"- 下载媒体: {'是' if download_media else '否'}\n")
            log.write(f"- 下载视频: {'是' if download_videos else '否'}\n\n")
            log.write("## 处理结果\n\n")
        
        # 处理每个URL
        for i, url in enumerate(urls):
            logger.info(f"[{i+1}/{len(urls)}] 处理文章: {url}")
            
            try:
                # 将URL添加到历史记录
                config.add_url_to_history(url)
                
                # 生成文章唯一ID
                article_id = f"article_{i+1:03d}_{timestamp}"
                
                # 创建文章子文件夹
                article_folder = os.path.join(batch_folder, article_id)
                os.makedirs(article_folder, exist_ok=True)
                
                # 设置文章媒体文件夹
                article_media_folder = os.path.join(media_folder, article_id) if download_media else None
                
                # 获取文章信息
                result = self.get_article_info(
                    url, 
                    download_media=download_media, 
                    media_folder=article_media_folder if article_media_folder else "", 
                    download_videos=download_videos
                )
                
                if not result or "error" in result:
                    error_msg = result.get("message", "未知错误") if result else "获取文章失败"
                    logger.error(f"处理失败 [URL: {url}, 错误: {error_msg}]")
                    
                    # 记录失败结果
                    with open(batch_log, 'a', encoding='utf-8') as log:
                        log.write(f"### {i+1}. ❌ 失败: {url}\n")
                        log.write(f"- 错误: {error_msg}\n\n")
                    
                    failed_count += 1
                    results.append({
                        "url": url,
                        "success": False,
                        "error": error_msg
                    })
                    continue
                
                # 处理成功，保存各种格式
                title = result.get("title", f"未命名文章_{article_id}")
                files_saved = []
                
                # 保存JSON格式
                if "json" in formats:
                    json_path = os.path.join(article_folder, f"{article_id}.json")
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    files_saved.append(("JSON", json_path))
                
                # 保存文本格式
                if "text" in formats:
                    text_path = os.path.join(article_folder, f"{article_id}.txt")
                    with open(text_path, 'w', encoding='utf-8') as f:
                        f.write(f"标题: {result['title']}\n")
                        f.write(f"作者: {result['author']}\n")
                        f.write(f"发布时间: {result['publish_time']}\n")
                        f.write(f"链接: {result['permanent_url']}\n\n")
                        
                        # 添加视频信息
                        if result['media_files']['videos']:
                            f.write("视频链接:\n")
                            for i, video in enumerate(result['media_files']['videos']):
                                if 'local_path' in video:
                                    f.write(f"视频 {i+1}: 已下载到 {video['local_path']}\n")
                                elif 'original_url' in video:
                                    f.write(f"视频 {i+1}: {video['original_url']}\n")
                            f.write("\n")
                        
                        f.write(result['full_content_text'])
                    files_saved.append(("文本", text_path))
                
                # 保存HTML格式
                if "html" in formats:
                    html_path = os.path.join(article_folder, f"{article_id}.html")
                    
                    # 准备视频HTML部分
                    videos_html = ""
                    if result['media_files']['videos']:
                        videos_html = "<div class='video-links'><h3>视频链接</h3><ul>"
                        for i, video in enumerate(result['media_files']['videos']):
                            videos_html += f"<li>"
                            
                            # 如果视频已下载，添加视频播放器
                            if 'local_path' in video:
                                local_path = os.path.relpath(video['local_path'], os.path.dirname(html_path)).replace('\\', '/')
                                videos_html += f"""
                                <div>
                                    <video controls style="max-width:100%; height:auto;">
                                        <source src="{local_path}" type="video/mp4">
                                        您的浏览器不支持视频标签
                                    </video>
                                    <p>已下载视频</p>
                                </div>
                                """
                            # 否则提供链接
                            elif 'original_url' in video:
                                videos_html += f"<a href='{video['original_url']}' target='_blank'>视频 {i+1}"
                                if 'type' in video:
                                    videos_html += f" ({video['type']})"
                                videos_html += "</a>"
                                
                                # 添加备选链接
                                if 'alternate_urls' in video:
                                    videos_html += "<div style='margin-left:20px; font-size:0.9em;'><p>备选链接：</p>"
                                    for j, alt_url in enumerate(video['alternate_urls']):
                                        if j > 0:  # 跳过第一个，因为和原始链接相同
                                            videos_html += f"<a href='{alt_url}' target='_blank'>备选 {j}</a><br>"
                                    videos_html += "</div>"
                            
                            videos_html += "</li>"
                        videos_html += "</ul></div>"
                    
                    with open(html_path, 'w', encoding='utf-8') as f:
                        f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{result['title']}</title>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ font-size: 24px; margin-bottom: 10px; }}
        .meta {{ color: #666; margin-bottom: 20px; }}
        img {{ max-width: 100%; height: auto; }}
        .media-info {{ margin-top: 20px; padding: 10px; background-color: #f5f5f5; border-radius: 5px; }}
        .video-links {{ margin-top: 20px; padding: 10px; background-color: #e9f7fe; border-radius: 5px; }}
        .video-links h3 {{ margin-top: 0; }}
        .video-links ul {{ padding-left: 20px; }}
        video {{ max-width: 100%; }}
    </style>
</head>
<body>
    <h1>{result['title']}</h1>
    <div class="meta">
        作者: {result['author']}<br>
        发布时间: {result['publish_time']}<br>
        原始链接: <a href="{result['original_url']}" target="_blank">{result['original_url']}</a>
    </div>
    
    {videos_html}
    
    <div class="content">
        {result['content_html']}
    </div>
    
    {f'''<div class="media-info">
        <h3>媒体文件信息</h3>
        <p>图片数量: {len(result['media_files']['images'])}</p>
        <p>视频数量: {len(result['media_files']['videos'])}</p>
    </div>''' if download_media else ''}
</body>
</html>""")
                    files_saved.append(("HTML", html_path))
                
                # 保存Markdown格式
                if "markdown" in formats:
                    md_path = os.path.join(article_folder, f"{article_id}.md")
                    self.export_to_markdown(result, md_path)
                    files_saved.append(("Markdown", md_path))
                
                # 统计媒体文件
                image_count = len(result['media_files']['images'])
                video_count = len(result['media_files']['videos'])
                downloaded_videos = sum(1 for v in result['media_files']['videos'] if 'local_path' in v)
                
                # 记录成功结果
                with open(batch_log, 'a', encoding='utf-8') as log:
                    log.write(f"### {i+1}. ✅ 成功: [{title}]({url})\n")
                    log.write(f"- 作者: {result['author']}\n")
                    log.write(f"- 发布时间: {result['publish_time']}\n")
                    log.write(f"- 已保存格式: {', '.join([f[0] for f in files_saved])}\n")
                    
                    if download_media:
                        log.write(f"- 图片: {image_count}张\n")
                        if download_videos:
                            log.write(f"- 视频: {video_count}个 (成功下载: {downloaded_videos}个)\n")
                        else:
                            log.write(f"- 视频: {video_count}个\n")
                    
                    # 添加文件链接列表
                    if files_saved:
                        log.write("- 文件列表:\n")
                        for format_name, file_path in files_saved:
                            rel_path = os.path.relpath(file_path, batch_folder).replace('\\', '/')
                            log.write(f"  - {format_name}: [{os.path.basename(file_path)}]({rel_path})\n")
                    
                    log.write("\n")
                
                # 更新统计
                success_count += 1
                results.append({
                    "url": url,
                    "success": True,
                    "title": title,
                    "files": files_saved,
                    "image_count": image_count,
                    "video_count": video_count
                })
                
                logger.info(f"成功处理文章: {title}")
                
            except Exception as e:
                logger.error(f"处理文章时出错 [URL: {url}, 错误: {str(e)}]")
                
                # 记录错误
                with open(batch_log, 'a', encoding='utf-8') as log:
                    log.write(f"### {i+1}. ❌ 失败: {url}\n")
                    log.write(f"- 错误: {str(e)}\n\n")
                
                failed_count += 1
                results.append({
                    "url": url,
                    "success": False,
                    "error": str(e)
                })
        
        # 更新批处理摘要
        with open(batch_log, 'a', encoding='utf-8') as log:
            log.write(f"\n## 汇总\n\n")
            log.write(f"- 总计: {len(urls)} 篇文章\n")
            log.write(f"- 成功: {success_count} 篇\n")
            log.write(f"- 失败: {failed_count} 篇\n")
            
            if failed_count > 0:
                log.write("\n### 失败列表\n\n")
                for i, result in enumerate([r for r in results if not r["success"]]):
                    log.write(f"{i+1}. {result['url']} - {result.get('error', '未知错误')}\n")
        
        logger.info(f"批量处理完成 [总计: {len(urls)}, 成功: {success_count}, 失败: {failed_count}]")
        
        return {
            "success": success_count,
            "failed": failed_count,
            "total": len(urls),
            "batch_folder": batch_folder,
            "batch_log": batch_log,
            "results": results
        }

def main():
    parser = argparse.ArgumentParser(description='爬取微信文章内容')
    
    # 输入参数
    input_group = parser.add_argument_group('输入选项')
    input_group.add_argument('-u', '--url', help='微信文章URL')
    input_group.add_argument('-f', '--file', help='包含多个URL的文件，每行一个URL')
    input_group.add_argument('-b', '--batch', action='store_true', help='批量模式处理多个URL')
    
    # 输出参数
    output_group = parser.add_argument_group('输出选项')
    output_group.add_argument('-o', '--output', default='article_content.json', help='输出文件名 (默认: article_content.json)')
    output_group.add_argument('-d', '--output_dir', default='outputs', help='输出文件保存文件夹 (默认: outputs)')
    output_group.add_argument('-t', '--text', action='store_true', help='同时生成纯文本文件')
    output_group.add_argument('-html', '--html', action='store_true', help='同时生成HTML文件')
    output_group.add_argument('-md', '--markdown', action='store_true', help='同时生成Markdown文件')
    
    # 媒体参数
    media_group = parser.add_argument_group('媒体选项')
    media_group.add_argument('-m', '--media', action='store_true', help='下载文章中的图片和视频')
    media_group.add_argument('-v', '--video', action='store_true', help='尝试下载视频文件 (需要安装 yt-dlp)')
    media_group.add_argument('--media_folder', default='media', help='媒体文件保存文件夹 (默认: media)')
    
    # 网络参数
    network_group = parser.add_argument_group('网络选项')
    network_group.add_argument('-p', '--proxy', help='使用代理服务器 (格式: http://127.0.0.1:7890)')
    network_group.add_argument('-r', '--retry', type=int, default=3, help='请求失败重试次数 (默认: 3)')
    network_group.add_argument('--timeout', type=int, default=10, help='请求超时时间(秒) (默认: 10)')
    
    # 解析参数
    args = parser.parse_args()
    
    # 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 检查参数有效性
    if not args.url and not args.file and not args.batch:
        parser.error("必须提供 -u/--url 或 -f/--file 参数指定要爬取的文章")
    
    # 处理输出格式
    formats = []
    if args.text:
        formats.append("text")
    if args.html:
        formats.append("html")
    if args.markdown:
        formats.append("markdown")
    # 总是添加JSON格式
    if "json" not in formats:
        formats.append("json")
    
    # 打印配置信息
    logger.info("微信文章爬虫启动")
    logger.info(f"代理设置: {args.proxy if args.proxy else '无'}")
    logger.info(f"下载媒体: {'是' if args.media else '否'}")
    logger.info(f"下载视频: {'是' if args.video else '否'}")
    logger.info(f"输出格式: {', '.join(formats)}")
    
    # 创建爬虫实例
    crawler = WeChatArticleCrawler(
        proxy=args.proxy,
        timeout=args.timeout,
        retry_times=args.retry,
        retry_delay=2
    )
    
    # 批量处理模式
    if args.batch or args.file:
        urls = []
        
        # 从文件读取URL
        if args.file:
            try:
                with open(args.file, 'r', encoding='utf-8') as f:
                    urls = [line.strip() for line in f if line.strip() and line.strip().startswith('http')]
                logger.info(f"从文件 {args.file} 中读取了 {len(urls)} 个URL")
            except Exception as e:
                logger.error(f"读取URL文件失败: {e}")
                return
        
        # 单URL添加到批处理
        if args.url:
            urls.append(args.url)
            
        # 检查URL列表
        if not urls:
            logger.error("没有有效的URL可供处理")
            return
            
        # 去除重复URL并过滤无效URL
        urls = list(set([url for url in urls if url.startswith('http')]))
        logger.info(f"准备批量处理 {len(urls)} 个URL")
        
        # 将所有URL添加到历史记录
        for url in urls:
            config.add_url_to_history(url)
        
        # 执行批量处理
        batch_result = crawler.batch_process(
            urls=urls,
            output_dir=args.output_dir,
            formats=formats,
            download_media=args.media,
            download_videos=args.video
        )
        
        # 打印批处理结果
        logger.info(f"批量处理完成 [成功: {batch_result['success']}/{batch_result['total']}]")
        logger.info(f"结果保存在: {batch_result['batch_folder']}")
        logger.info(f"汇总报告: {batch_result['batch_log']}")
        
    # 单篇文章处理模式
    else:
        # 将URL添加到历史记录
        config.add_url_to_history(args.url)
        
        # 生成带时间戳的文件名
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base_filename = os.path.splitext(args.output)[0]
        timestamped_filename = f"{base_filename}_{timestamp}"
        
        # 创建文章专属文件夹
        article_folder = os.path.join(args.output_dir, f"article_{timestamp}")
        os.makedirs(article_folder, exist_ok=True)
        
        # 设置完整的输出文件路径（都在article_folder下）
        json_output = os.path.join(article_folder, f"{timestamped_filename}.json")
        text_output = os.path.join(article_folder, f"{timestamped_filename}.txt")
        html_output = os.path.join(article_folder, f"{timestamped_filename}.html")
        md_output = os.path.join(article_folder, f"{timestamped_filename}.md")
        
        # 设置媒体文件夹为文章目录的子文件夹
        media_folder = os.path.join(article_folder, "media")
        if args.media:
            os.makedirs(media_folder, exist_ok=True)
        
        # 获取文章信息
        result = crawler.get_article_info(args.url, download_media=args.media, media_folder=media_folder, download_videos=args.video)
        
        if result:
            print(f"\n文章标题: {result['title']}")
            print(f"作者: {result['author']}")
            print(f"发布时间: {result['publish_time']}")
            print(f"永久链接: {result['permanent_url']}")
            print(f"\n预览内容: \n{result['content_text'][:200]}...\n")
            
            # 打印媒体文件信息
            if args.media:
                print(f"图片数量: {len(result['media_files']['images'])}")
                print(f"视频数量: {len(result['media_files']['videos'])}")
                
                # 打印视频信息
                if result['media_files']['videos']:
                    print("\n视频信息:")
                    for i, video in enumerate(result['media_files']['videos']):
                        print(f"视频 {i+1}:")
                        if 'type' in video:
                            print(f"  类型: {video['type']}")
                        if 'original_url' in video:
                            print(f"  URL: {video['original_url']}")
                        if 'vid' in video:
                            print(f"  VID: {video['vid']}")
                        if 'local_path' in video:
                            print(f"  已下载到: {video['local_path']}")
            
            # 保存完整结果到JSON文件
            with open(json_output, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"完整内容已保存到: {json_output}")
            
            # 如果需要，保存纯文本版本
            if args.text:
                with open(text_output, 'w', encoding='utf-8') as f:
                    f.write(f"标题: {result['title']}\n")
                    f.write(f"作者: {result['author']}\n")
                    f.write(f"发布时间: {result['publish_time']}\n")
                    f.write(f"链接: {result['permanent_url']}\n\n")
                    # 添加视频信息到文本文件
                    if result['media_files']['videos']:
                        f.write("视频链接:\n")
                        for i, video in enumerate(result['media_files']['videos']):
                            if 'local_path' in video:
                                f.write(f"视频 {i+1}: 已下载到 {video['local_path']}\n")
                            elif 'original_url' in video:
                                f.write(f"视频 {i+1}: {video['original_url']}\n")
                        f.write("\n")
                    f.write(result['full_content_text'])
                print(f"纯文本内容已保存到: {text_output}")
            
            # 如果需要，保存HTML版本
            if args.html:
                videos_html = ""
                if result['media_files']['videos']:
                    videos_html = "<div class='video-links'><h3>视频链接</h3><ul>"
                    for i, video in enumerate(result['media_files']['videos']):
                        videos_html += f"<li>"
                        
                        # 如果视频已下载，添加视频播放器
                        if 'local_path' in video:
                            local_path = os.path.relpath(video['local_path'], os.path.dirname(html_output)).replace('\\', '/')
                            videos_html += f"""
                            <div>
                                <video controls style="max-width:100%; height:auto;">
                                    <source src="{local_path}" type="video/mp4">
                                    您的浏览器不支持视频标签
                                </video>
                                <p>已下载视频</p>
                            </div>
                            """
                        # 否则提供链接
                        elif 'original_url' in video:
                            videos_html += f"<a href='{video['original_url']}' target='_blank'>视频 {i+1}"
                            if 'type' in video:
                                videos_html += f" ({video['type']})"
                            videos_html += "</a>"
                            
                            # 添加备选链接
                            if 'alternate_urls' in video:
                                videos_html += "<div style='margin-left:20px; font-size:0.9em;'><p>备选链接：</p>"
                                for j, alt_url in enumerate(video['alternate_urls']):
                                    if j > 0:  # 跳过第一个，因为和原始链接相同
                                        videos_html += f"<a href='{alt_url}' target='_blank'>备选 {j}</a><br>"
                                videos_html += "</div>"
                        
                        videos_html += "</li>"
                    videos_html += "</ul></div>"
                
                with open(html_output, 'w', encoding='utf-8') as f:
                    f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{result['title']}</title>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ font-size: 24px; margin-bottom: 10px; }}
        .meta {{ color: #666; margin-bottom: 20px; }}
        img {{ max-width: 100%; height: auto; }}
        .media-info {{ margin-top: 20px; padding: 10px; background-color: #f5f5f5; border-radius: 5px; }}
        .video-links {{ margin-top: 20px; padding: 10px; background-color: #e9f7fe; border-radius: 5px; }}
        .video-links h3 {{ margin-top: 0; }}
        .video-links ul {{ padding-left: 20px; }}
        video {{ max-width: 100%; }}
    </style>
</head>
<body>
    <h1>{result['title']}</h1>
    <div class="meta">
        作者: {result['author']}<br>
        发布时间: {result['publish_time']}<br>
        原始链接: <a href="{result['original_url']}" target="_blank">{result['original_url']}</a>
    </div>
    
    {videos_html}
    
    <div class="content">
        {result['content_html']}
    </div>
    
    {f'''<div class="media-info">
        <h3>媒体文件信息</h3>
        <p>图片数量: {len(result['media_files']['images'])}</p>
        <p>视频数量: {len(result['media_files']['videos'])}</p>
    </div>''' if args.media else ''}
</body>
</html>""")
                    print(f"HTML内容已保存到: {html_output}")
                
                # 如果需要，保存Markdown版本
                if args.markdown:
                    if crawler.export_to_markdown(result, md_output):
                        print(f"Markdown内容已保存到: {md_output}")
        else:
            print(f"爬取文章失败: {args.url}")

if __name__ == "__main__":
    main() 