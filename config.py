import os
import json
import time

class Config:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        # 默认配置
        self.default_config = {
            "output_dir": "outputs",
            "media_folder": "media",
            "default_formats": ["文本", "HTML", "Markdown"],
            "download_media": True,
            "download_videos": False,
            "proxy": "",
            "retry_times": 3,
            "retry_delay": 2,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "timeout": 10,
            "last_used_urls": [],
            "max_url_history": 10
        }
        # 加载配置
        self.config = self.load_config()
    
    def load_config(self):
        """加载配置文件"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return {**self.default_config, **json.load(f)}
            except Exception as e:
                print(f"加载配置文件失败: {e}，使用默认配置")
                return self.default_config.copy()
        else:
            return self.default_config.copy()
    
    def save_config(self):
        """保存配置到文件"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            return False
    
    def update_config(self, **kwargs):
        """更新配置"""
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
        return self.save_config()
    
    def get(self, key, default=None):
        """获取配置项"""
        return self.config.get(key, default)
    
    def add_url_to_history(self, url):
        """添加URL到历史记录"""
        if not url:
            return
            
        urls = self.config.get("last_used_urls", [])
        # 如果URL已存在，先移除
        if url in urls:
            urls.remove(url)
        # 添加到列表开头
        urls.insert(0, url)
        # 限制历史记录数量
        max_history = self.config.get("max_url_history", 10)
        self.config["last_used_urls"] = urls[:max_history]
        self.save_config()

# 创建全局配置实例
config = Config() 