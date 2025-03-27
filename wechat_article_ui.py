import gradio as gr
import json
import os
import subprocess
import time
import sys
import logging
import re

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 添加当前目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from wechat_article_crawler import WeChatArticleCrawler
from config import config

# 检查是否安装了yt-dlp
def check_ytdlp_installed():
    try:
        import yt_dlp
        return True
    except ImportError:
        return False

# 创建爬虫实例 - 使用配置中的设置
def create_crawler(proxy=None, timeout=None, retry_times=None):
    """基于当前配置创建爬虫实例"""
    # 如果没有指定参数，则使用配置中的值
    if proxy is None:
        proxy = config.get("proxy", "")
    if timeout is None:
        timeout = config.get("timeout", 10)
    if retry_times is None:
        retry_times = config.get("retry_times", 3)
        
    return WeChatArticleCrawler(
        proxy=proxy if proxy else None,
        timeout=timeout,
        retry_times=retry_times,
        retry_delay=config.get("retry_delay", 2)
    )

# 创建爬虫实例
crawler = WeChatArticleCrawler()

def crawl_article(url, output_format, download_media, download_videos, proxy=""):
    """爬取微信文章并根据选择的格式保存"""
    if not url or not url.startswith("https://mp.weixin.qq.com"):
        return "请输入有效的微信文章链接", None, None, None
    
    try:
        # 将URL添加到历史记录
        config.add_url_to_history(url)
        
        # 创建输出目录
        output_dir = config.get("output_dir", "outputs")
        os.makedirs(output_dir, exist_ok=True)
        
        # 生成时间戳
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        
        # 为当前文章创建专门的文件夹
        article_folder = os.path.join(output_dir, f"article_{timestamp}")
        os.makedirs(article_folder, exist_ok=True)
        
        # 准备媒体文件夹（在文章文件夹下创建media子文件夹）
        media_folder = os.path.join(article_folder, "media")
        if download_media:
            os.makedirs(media_folder, exist_ok=True)
        
        # 检查是否要下载视频但未安装yt-dlp
        if download_videos and not check_ytdlp_installed():
            return "下载视频需要安装yt-dlp，请运行 `pip install yt-dlp` 后再试", None, None, None
        
        # 创建爬虫实例
        crawler = create_crawler(proxy=proxy)
        
        # 获取文章信息
        logger.info(f"开始爬取文章: {url}")
        result = crawler.get_article_info(url, download_media=download_media, 
                                        media_folder=media_folder, 
                                        download_videos=download_videos)
        
        if not result:
            return "爬取文章失败，请检查链接是否有效", None, None, None
            
        if "error" in result and result["error"]:
            return f"爬取文章失败: {result.get('message', '未知错误')}", None, None, None
        
        # 准备带时间戳的输出文件名
        base_filename = "article_content"
        timestamped_filename = f"{base_filename}_{timestamp}"
        
        # 设置完整的输出文件路径（都在article_folder下）
        json_filename = os.path.join(article_folder, f"{timestamped_filename}.json")
        text_filename = os.path.join(article_folder, f"{timestamped_filename}.txt")
        html_filename = os.path.join(article_folder, f"{timestamped_filename}.html")
        md_filename = os.path.join(article_folder, f"{timestamped_filename}.md")
        
        # 保存JSON文件（始终保存）
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        # 准备输出结果
        output_files = [f"JSON文件已保存: {json_filename}"]
        preview_html = None
        download_files = [json_filename]
        
        # 将中文格式名称转换为程序使用的格式名称
        format_mapping = {
            "文本": "text",
            "HTML": "html",
            "Markdown": "markdown"
        }
        
        formats = [format_mapping.get(fmt, fmt.lower()) for fmt in output_format]
        
        # 如果选择了文本格式
        if "text" in formats:
            with open(text_filename, 'w', encoding='utf-8') as f:
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
            output_files.append(f"文本文件已保存: {text_filename}")
            download_files.append(text_filename)
        
        # 如果选择了HTML格式
        if "html" in formats:
            # 准备视频HTML部分
            videos_html = ""
            if result['media_files']['videos']:
                videos_html = "<div class='video-links'><h3>视频链接</h3><ul>"
                for i, video in enumerate(result['media_files']['videos']):
                    videos_html += f"<li>"
                    
                    # 如果视频已下载，添加视频播放器
                    if 'local_path' in video:
                        local_path = os.path.relpath(video['local_path'], os.path.dirname(html_filename)).replace('\\', '/')
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
            
            with open(html_filename, 'w', encoding='utf-8') as f:
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
            output_files.append(f"HTML文件已保存: {html_filename}")
            download_files.append(html_filename)
            
            # 生成HTML预览
            preview_html = f"""
            <h1>{result['title']}</h1>
            <div style="color: #666; margin-bottom: 20px;">
                作者: {result['author']}<br>
                发布时间: {result['publish_time']}
            </div>
            """
            
            # 添加视频预览
            if result['media_files']['videos']:
                preview_html += """
                <div style="margin: 15px 0; padding: 10px; background-color: #e9f7fe; border-radius: 5px;">
                    <h3 style="margin-top: 0;">视频信息</h3>
                    <ul>
                """
                for i, video in enumerate(result['media_files']['videos']):
                    preview_html += f"<li>"
                    
                    # 如果视频已下载，显示本地视频
                    if 'local_path' in video:
                        local_path = os.path.relpath(video['local_path'], '.').replace('\\', '/')
                        preview_html += f"""
                        <div>
                            <video controls style="max-width:100%; height:auto;">
                                <source src="{local_path}" type="video/mp4">
                                您的浏览器不支持视频标签
                            </video>
                            <p>已下载视频 {i+1}</p>
                        </div>
                        """
                    # 否则显示链接
                    elif 'original_url' in video:
                        preview_html += f"""<a href="{video['original_url']}" target="_blank">视频 {i+1}</a>"""
                        
                        # 添加备选链接
                        if 'alternate_urls' in video and len(video['alternate_urls']) > 1:
                            preview_html += """<div style="margin-left:20px; font-size:0.9em;">
                            <p>备选链接:</p>"""
                            for j, alt_url in enumerate(video['alternate_urls']):
                                if j > 0:  # 跳过第一个
                                    preview_html += f"""<a href="{alt_url}" target="_blank">备选 {j}</a><br>"""
                            preview_html += "</div>"
                    
                    preview_html += "</li>"
                preview_html += """
                    </ul>
                </div>
                """
            
            # 添加内容预览
            preview_html += f"""
            <div>
                {result['content_text'][:300]}...
            </div>
            """
        
        # 如果选择了Markdown格式
        if "markdown" in formats:
            crawler.export_to_markdown(result, md_filename)
            output_files.append(f"Markdown文件已保存: {md_filename}")
            download_files.append(md_filename)
        
        # 添加媒体文件到下载列表
        if download_media:
            # 添加图片
            for img in result['media_files']['images']:
                if 'local_path' in img:
                    download_files.append(img['local_path'])
            
            # 添加视频
            if download_videos:
                for video in result['media_files']['videos']:
                    if 'local_path' in video:
                        download_files.append(video['local_path'])
        
        # 准备输出消息
        media_info = ""
        if download_media:
            img_count = len(result['media_files']['images'])
            video_count = len(result['media_files']['videos'])
            
            # 统计下载成功的视频数
            downloaded_videos = sum(1 for v in result['media_files']['videos'] if 'local_path' in v)
            
            media_info = f"\n\n**媒体文件:**\n- 图片: {img_count}张"
            
            if download_videos:
                media_info += f"\n- 视频: {video_count}个 (成功下载: {downloaded_videos}个)"
            else:
                media_info += f"\n- 视频: {video_count}个"
            
            # 如果有视频，添加视频链接和本地路径
            if video_count > 0:
                media_info += "\n\n**视频信息:**"
                for i, video in enumerate(result['media_files']['videos']):
                    video_type = f" ({video.get('type', '未知类型')})" if 'type' in video else ""
                    
                    if 'local_path' in video:
                        media_info += f"\n- 视频 {i+1}{video_type}: 已下载到本地"
                    elif 'original_url' in video:
                        media_info += f"\n- [视频 {i+1}{video_type}]({video['original_url']})"
                        
                        # 添加备选链接
                        if 'alternate_urls' in video and len(video['alternate_urls']) > 1:
                            media_info += "\n  备选链接:"
                            for j, alt_url in enumerate(video['alternate_urls']):
                                if j > 0:  # 跳过第一个
                                    media_info += f"\n  - [备选 {j}]({alt_url})"
        
        output_message = f"""
## 爬取成功！

**标题:** {result['title']}
**作者:** {result['author']}
**内容预览:** 
{result['content_text'][:200]}...

**输出时间:** {timestamp}
**已保存格式:** {', '.join(output_format)}
**输出文件:**
{'、'.join(output_files)}{media_info}
        """
        
        logger.info(f"成功爬取文章: {result['title']}")
        return output_message, preview_html, download_files, result['title']
    
    except Exception as e:
        logger.error(f"爬取文章时出错: {str(e)}")
        return f"发生错误: {str(e)}", None, None, None

def batch_crawl_articles(urls_text, output_format, download_media, download_videos, proxy=""):
    """批量爬取多个微信文章"""
    # 解析输入的URL列表
    urls = []
    for line in urls_text.strip().split('\n'):
        url = line.strip()
        if url and url.startswith("https://mp.weixin.qq.com"):
            urls.append(url)
    
    if not urls:
        return "未找到有效的微信文章链接，请确保每行一个链接，并以 https://mp.weixin.qq.com 开头", None, None
    
    try:
        logger.info(f"开始批量爬取 {len(urls)} 篇文章")
        
        # 将中文格式名称转换为程序使用的格式名称
        format_mapping = {
            "文本": "text",
            "HTML": "html",
            "Markdown": "markdown"
        }
        
        formats = [format_mapping.get(fmt, fmt.lower()) for fmt in output_format]
        
        # 创建爬虫实例
        crawler = create_crawler(proxy=proxy)
        
        # 执行批量爬取
        batch_result = crawler.batch_process(
            urls=urls,
            output_dir=config.get("output_dir", "outputs"),
            formats=formats,
            download_media=download_media,
            download_videos=download_videos
        )
        
        # 准备下载文件列表
        download_files = [batch_result['batch_log']]
        
        # 生成结果报告
        output_message = f"""
## 批量爬取完成！

- **处理文章总数:** {batch_result['total']} 篇
- **成功:** {batch_result['success']} 篇
- **失败:** {batch_result['failed']} 篇
- **批处理文件夹:** {batch_result['batch_folder']}
- **汇总报告:** {batch_result['batch_log']}

**输出格式:** {', '.join(output_format)}
**下载媒体:** {'是' if download_media else '否'}
**下载视频:** {'是' if download_videos else '否'}
        """
        
        # 如果有失败的文章，添加失败列表
        if batch_result['failed'] > 0:
            output_message += "\n\n### 失败列表:\n"
            for i, result in enumerate([r for r in batch_result['results'] if not r['success']]):
                output_message += f"{i+1}. {result['url']} - {result.get('error', '未知错误')}\n"
        
        # 生成简单的HTML预览
        preview_html = f"""
        <h2>批量爬取完成</h2>
        <p>处理文章总数: {batch_result['total']} 篇</p>
        <p>成功: {batch_result['success']} 篇</p>
        <p>失败: {batch_result['failed']} 篇</p>
        <p>输出格式: {', '.join(output_format)}</p>
        <p>可在下方下载汇总报告查看详细信息</p>
        """
        
        # 添加成功爬取的文章列表
        if batch_result['success'] > 0:
            preview_html += "<h3>成功爬取的文章:</h3><ul>"
            for result in [r for r in batch_result['results'] if r['success']]:
                title = result.get('title', result['url'])
                preview_html += f"<li>{title}</li>"
            preview_html += "</ul>"
        
        logger.info(f"批量爬取完成，成功: {batch_result['success']}/{batch_result['total']}")
        return output_message, preview_html, download_files
    
    except Exception as e:
        logger.error(f"批量爬取文章时出错: {str(e)}")
        return f"批量爬取过程中发生错误: {str(e)}", None, None

# 检查是否安装了yt-dlp并提供安装提示
def check_and_install_ytdlp():
    try:
        import yt_dlp
        return "yt-dlp 已安装，可以下载视频", True
    except ImportError:
        return "未安装 yt-dlp，无法下载视频。请运行 `pip install yt-dlp` 来安装", False

# 保存配置更改
def save_config_changes(output_dir, media_folder, proxy, timeout, retry_times):
    """保存用户配置更改"""
    config.update_config(
        output_dir=output_dir,
        media_folder=media_folder,
        proxy=proxy,
        timeout=int(timeout) if timeout else 10,
        retry_times=int(retry_times) if retry_times else 3
    )
    return "配置已保存"

# 创建Gradio界面
with gr.Blocks(title="微信文章爬虫工具", theme=gr.themes.Soft()) as app:
    # 状态变量
    article_title = gr.Textbox(visible=False)  # 用于存储文章标题
    ytdlp_status, ytdlp_installed = check_and_install_ytdlp()
    
    # 顶部标题和导航
    with gr.Row():
        gr.Markdown("# 微信文章爬虫工具")
    
    # 标签页
    with gr.Tabs() as tabs:
        # 单篇爬取标签页
        with gr.TabItem("单篇爬取"):
            with gr.Row():
                with gr.Column(scale=3):
                    url_input = gr.Textbox(
                        label="微信文章链接", 
                        placeholder="请输入以 https://mp.weixin.qq.com 开头的链接",
                        lines=1
                    )
                    
                    # 在URL输入框下添加历史记录下拉列表
                    url_history = gr.Dropdown(
                        choices=config.get("last_used_urls", []),
                        label="历史记录",
                        interactive=True,
                    )
                    
                    output_format = gr.CheckboxGroup(
                        ["文本", "HTML", "Markdown"], 
                        label="输出格式（可多选）", 
                        value=config.get("default_formats", ["文本", "HTML", "Markdown"])
                    )
                    
                    with gr.Row():
                        download_media = gr.Checkbox(
                            label="下载图片", 
                            value=config.get("download_media", True),
                            info="勾选后将下载文章中的所有图片"
                        )
                        download_videos = gr.Checkbox(
                            label="下载视频", 
                            value=config.get("download_videos", ytdlp_installed),
                            info=ytdlp_status
                        )
                    
                    proxy_input = gr.Textbox(
                        label="代理设置（可选）",
                        placeholder="例如: http://127.0.0.1:7890",
                        value=config.get("proxy", ""),
                        lines=1
                    )
                    
                    crawl_button = gr.Button("开始爬取", variant="primary")
                
                with gr.Column(scale=2):
                    gr.Markdown("### 使用说明")
                    gr.Markdown("""
                    1. 输入微信公众号文章的链接
                    2. 选择需要的输出格式（默认同时输出文本、HTML和Markdown）
                    3. 选择是否下载文章中的图片和视频
                       - 视频下载需要安装 yt-dlp (`pip install yt-dlp`)
                       - 部分视频可能无法下载，会提供在线链接
                    4. 可选：设置代理服务器以避免IP限制
                    5. 点击"开始爬取"按钮
                    6. 查看结果并下载文件
                    
                    **注意:** 
                    - 链接必须以 https://mp.weixin.qq.com 开头
                    - 所有输出文件将保存在 `outputs` 文件夹中，文件名带有时间戳
                    - 下载的图片和视频将保存在 `outputs/media/时间戳` 文件夹中
                    """)
            
            with gr.Row():
                with gr.Column(scale=1):
                    result_output = gr.Markdown(label="爬取结果")
                
                with gr.Column(scale=1):
                    html_preview = gr.HTML(label="HTML预览")
            
            file_output = gr.File(label="下载文件", file_count="multiple", interactive=False)
        
        # 批量爬取标签页
        with gr.TabItem("批量爬取"):
            with gr.Row():
                with gr.Column(scale=3):
                    urls_input = gr.Textbox(
                        label="微信文章链接列表", 
                        placeholder="请输入多个微信文章链接，每行一个链接",
                        lines=10
                    )
                    
                    batch_output_format = gr.CheckboxGroup(
                        ["文本", "HTML", "Markdown"], 
                        label="输出格式（可多选）", 
                        value=config.get("default_formats", ["文本", "HTML", "Markdown"])
                    )
                    
                    with gr.Row():
                        batch_download_media = gr.Checkbox(
                            label="下载图片", 
                            value=config.get("download_media", True),
                            info="勾选后将下载文章中的所有图片"
                        )
                        batch_download_videos = gr.Checkbox(
                            label="下载视频", 
                            value=config.get("download_videos", ytdlp_installed),
                            info=ytdlp_status
                        )
                    
                    batch_proxy_input = gr.Textbox(
                        label="代理设置（可选）",
                        placeholder="例如: http://127.0.0.1:7890",
                        value=config.get("proxy", ""),
                        lines=1
                    )
                    
                    batch_crawl_button = gr.Button("开始批量爬取", variant="primary")
                
                with gr.Column(scale=2):
                    gr.Markdown("### 批量爬取说明")
                    gr.Markdown("""
                    1. 输入多个微信公众号文章链接，每行一个
                    2. 选择需要的输出格式
                    3. 设置下载选项
                    4. 点击"开始批量爬取"按钮
                    
                    **批量爬取特点：**
                    - 自动处理多篇文章
                    - 创建包含所有文章的批处理文件夹
                    - 生成汇总报告，方便查看结果
                    - 自动跳过处理失败的文章，继续处理其他文章
                    
                    **示例链接格式：**
                    ```
                    https://mp.weixin.qq.com/s/xxx
                    https://mp.weixin.qq.com/s/yyy
                    https://mp.weixin.qq.com/s/zzz
                    ```
                    """)
            
            batch_result_output = gr.Markdown(label="批量爬取结果")
            batch_preview = gr.HTML(label="批量结果预览")
            batch_file_output = gr.File(label="下载汇总报告", file_count="multiple", interactive=False)
        
        # 设置页面
        with gr.TabItem("设置"):
            gr.Markdown("### 爬虫设置")
            
            with gr.Row():
                with gr.Column():
                    settings_output_dir = gr.Textbox(
                        label="输出目录",
                        value=config.get("output_dir", "outputs"),
                        placeholder="输出文件保存位置"
                    )
                    
                    settings_media_folder = gr.Textbox(
                        label="媒体文件夹名称",
                        value=config.get("media_folder", "media"),
                        placeholder="图片和视频保存的子文件夹名"
                    )
                    
                    settings_proxy = gr.Textbox(
                        label="全局代理设置",
                        value=config.get("proxy", ""),
                        placeholder="例如: http://127.0.0.1:7890"
                    )
                
                with gr.Column():
                    settings_timeout = gr.Number(
                        label="请求超时时间（秒）",
                        value=config.get("timeout", 10),
                        precision=0
                    )
                    
                    settings_retry_times = gr.Number(
                        label="请求重试次数",
                        value=config.get("retry_times", 3),
                        precision=0
                    )
                    
                    save_settings_button = gr.Button("保存设置", variant="primary")
                    settings_status = gr.Markdown("")
    
    # 设置事件处理
    
    # URL历史记录加载
    def update_url_from_history(history_url):
        return history_url
    
    url_history.change(
        fn=update_url_from_history,
        inputs=[url_history],
        outputs=[url_input]
    )
    
    # 单篇爬取
    crawl_button.click(
        fn=crawl_article, 
        inputs=[url_input, output_format, download_media, download_videos, proxy_input], 
        outputs=[result_output, html_preview, file_output, article_title]
    )
    
    # 批量爬取
    batch_crawl_button.click(
        fn=batch_crawl_articles,
        inputs=[urls_input, batch_output_format, batch_download_media, batch_download_videos, batch_proxy_input],
        outputs=[batch_result_output, batch_preview, batch_file_output]
    )
    
    # 保存设置
    save_settings_button.click(
        fn=save_config_changes,
        inputs=[settings_output_dir, settings_media_folder, settings_proxy, settings_timeout, settings_retry_times],
        outputs=[settings_status]
    )
    
    # 添加示例
    gr.Examples(
        examples=[
            ["https://mp.weixin.qq.com/s/ONQIatEPjSux5VTbvyrqUw", ["文本", "HTML", "Markdown"], True, ytdlp_installed, ""],
        ],
        inputs=[url_input, output_format, download_media, download_videos, proxy_input],
    )

if __name__ == "__main__":
    # 启动前确保配置路径存在
    os.makedirs(config.get("output_dir", "outputs"), exist_ok=True)
    
    # 启动Web界面
    app.launch(share=False, inbrowser=True) 