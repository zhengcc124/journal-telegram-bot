# Munin 日记模式技术架构 Review 报告

## 📋 执行摘要

本报告对 Munin 日记模式的需求变更进行全面的技术架构 Review。核心变更包括：**触发逻辑从"24小时无新消息"改为"跨天自然日边界触发"**，以及引入数据库支持多数据源扩展。

**关键结论**：
- ✅ 当前架构适合 MVP，但需要引入数据库层支持扩展
- ✅ 推荐采用"Event Sourcing + 聚合"模式处理日记合并
- ⚠️ 豆瓣 API 已关闭，需要特殊处理方案
- ⚠️ 多服务协调需要统一的任务调度中心

---

## 1. 架构设计评估

### 1.1 当前架构分析

```
┌─────────────────────────────────────────────────────────────────┐
│                        当前架构 (单体)                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Telegram Bot                                              │
│        │                                                    │
│        ▼                                                    │
│   ┌─────────────┐    ┌─────────────┐    ┌──────────────┐   │
│   │  Message    │───▶│   GitHub    │───▶│    Issue     │   │
│   │  Handler    │    │   Client    │    │   Storage    │   │
│   └─────────────┘    └─────────────┘    └──────────────┘   │
│                                                │             │
│                                                ▼             │
│                                         GitHub Actions       │
│                                         (Publish to MD)      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**优点**：
- 简单直接，运维成本低
- GitHub Issue 天然支持评论和版本历史
- 无需维护数据库

**缺点**：
- 状态丢失风险（进程重启会丢失未提交的消息缓冲）
- 无法支持跨天合并（需要持久化状态）
- 不支持多数据源聚合
- 无法高效查询和统计

### 1.2 扩展架构设计

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        推荐架构 (数据库驱动)                                │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                      API Gateway / Bot Layer                     │   │
│   │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐  │   │
│   │  │  Telegram  │  │   Douban   │  │  Readwise  │  │  Strava  │  │   │
│   │  │    Bot     │  │   Spider   │  │   Syncer   │  │  OAuth   │  │   │
│   │  └────────────┘  └────────────┘  └────────────┘  └──────────┘  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                     │
│                                    ▼                                     │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                      Message Queue (Redis/RabbitMQ)              │   │
│   │              异步任务队列，支持重试和并发控制                      │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                     │
│                                    ▼                                     │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                      Core Service Layer                          │   │
│   │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐  │   │
│   │  │  Journal   │  │   Entry    │  │    Sync    │  │  AI      │  │   │
│   │  │  Manager   │  │  Collector │  │ Scheduler  │  │ Summary  │  │   │
│   │  └────────────┘  └────────────┘  └────────────┘  └──────────┘  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                     │
│                                    ▼                                     │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                      Data Layer                                  │   │
│   │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐  │   │
│   │  │   SQLite/  │  │   File     │  │   Cache    │  │  Vector  │  │   │
│   │  │  Postgres  │  │  Storage   │  │   (Redis)  │  │   Store  │  │   │
│   │  └────────────┘  └────────────┘  └────────────┘  └──────────┘  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                     │
│                                    ▼                                     │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                      Output Layer                                │   │
│   │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐  │   │
│   │  │   GitHub   │  │   Weekly   │  │    API     │  │ Export   │  │   │
│   │  │   Issue    │  │   Report   │  │  Endpoint  │  │  (PDF)   │  │   │
│   │  └────────────┘  └────────────┘  └────────────┘  └──────────┘  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### 1.3 是否需要服务拆分？

| 阶段 | 架构 | 适用场景 |
|------|------|----------|
| **MVP (当前)** | 单体应用 | 单一数据源，快速验证 |
| **Phase 1** | 单体 + 数据库 | 引入多数据源，需要持久化 |
| **Phase 2** | 模块化单体 | 清晰模块边界，代码复用 |
| **Phase 3** | 微服务 | 高频并发，多租户部署 |

**推荐**：采用 **模块化单体** 架构，通过清晰的模块划分实现"逻辑拆分"而非"物理拆分"。

---

## 2. 数据库 Schema 设计

### 2.1 核心实体关系图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           数据模型关系图                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐         ┌─────────────────┐         ┌────────────────┐ │
│  │     Users       │         │    Journals     │         │    Entries     │ │
│  ├─────────────────┤         ├─────────────────┤         ├────────────────┤ │
│  │ id (PK)         │◀───┐    │ id (PK)         │◀────┐   │ id (PK)        │ │
│  │ telegram_id     │    │    │ user_id (FK)    │─────┘   │ journal_id(FK) │ │
│  │ github_username │    │    │ date            │         │ source_type    │ │
│  │ created_at      │    │    │ status          │         │ source_id      │ │
│  │ settings        │    │    │ merged_at       │         │ content        │ │
│  └─────────────────┘    │    │ github_issue_no │         │ metadata       │ │
│                         │    │ ai_summary      │         │ created_at     │ │
│                         │    │ └───────────────┘         │ updated_at     │ │
│                         │                               │ └──────────────┘ │
│                         │         1:N                           │          │
│                         └───────────────────────────────────────┘          │
│                                                                             │
│  ┌─────────────────┐         ┌─────────────────┐         ┌────────────────┐ │
│  │  Sync Tasks     │         │  Sync Configs   │         │    Media       │ │
│  ├─────────────────┤         ├─────────────────┤         ├────────────────┤ │
│  │ id (PK)         │         │ id (PK)         │         │ id (PK)        │ │
│  │ user_id (FK)    │◀────────┤ user_id (FK)    │         │ entry_id (FK)  │ │
│  │ source_type     │         │ source_type     │         │ file_path      │ │
│  │ status          │         │ credentials     │         │ file_type      │ │
│  │ last_sync_at    │         │ sync_enabled    │         │ file_size      │ │
│  │ next_sync_at    │         │ sync_schedule   │         │ github_url     │ │
│  └─────────────────┘         └─────────────────┘         └────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 SQLAlchemy 模型定义

```python
# models/base.py
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, 
    ForeignKey, Boolean, JSON, Enum, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

Base = declarative_base()

# ============================================================================
# 枚举类型定义
# ============================================================================

from enum import Enum as PyEnum

class EntrySourceType(str, PyEnum):
    """数据源类型"""
    TELEGRAM = "telegram"
    DOUBAN = "douban"
    READWISE = "readwise"
    APPLE_HEALTH = "apple_health"
    STRAVA = "strava"
    MANUAL = "manual"

class JournalStatus(str, PyEnum):
    """日记状态"""
    COLLECTING = "collecting"      # 收集中
    PENDING_MERGE = "pending_merge" # 待合并
    MERGED = "merged"              # 已合并
    PUBLISHED = "published"        # 已发布到 GitHub

class EntryContentType(str, PyEnum):
    """条目内容类型"""
    TEXT = "text"
    IMAGE = "image"
    DOUBAN_MOVIE = "douban_movie"
    DOUBAN_BOOK = "douban_book"
    DOUBAN_MUSIC = "douban_music"
    READWISE_ARTICLE = "readwise_article"
    HEALTH_WORKOUT = "health_workout"
    STRAVA_ACTIVITY = "strava_activity"


# ============================================================================
# 数据模型
# ============================================================================

class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    telegram_username = Column(String(255))
    github_username = Column(String(255))
    github_repo = Column(String(255))
    timezone = Column(String(50), default="Asia/Shanghai")
    
    # 用户设置 (JSON 存储，灵活扩展)
    settings = Column(JSON, default={
        "auto_merge_enabled": True,
        "ai_summary_enabled": True,
        "weekly_report_enabled": True,
        "default_tags": ["journal"]
    })
    
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("UTC")))
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("UTC")), 
                        onupdate=lambda: datetime.now(ZoneInfo("UTC")))
    
    # 关系
    journals = relationship("Journal", back_populates="user")
    sync_configs = relationship("SyncConfig", back_populates="user")


class Journal(Base):
    """
    日记表 - 按自然日聚合的日记
    
    设计说明：
    - 每用户每天一条日记记录
    - 状态机: COLLECTING -> PENDING_MERGE -> MERGED -> PUBLISHED
    - github_issue_no 记录对应的 GitHub Issue
    """
    __tablename__ = "journals"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(DateTime, nullable=False, index=True)  # 日记日期 (时区相关)
    
    # 状态管理
    status = Column(Enum(JournalStatus), default=JournalStatus.COLLECTING)
    
    # GitHub 集成
    github_issue_no = Column(Integer)
    github_issue_url = Column(String(500))
    
    # AI 总结
    ai_summary = Column(Text)  # AI 生成的当日总结
    ai_summary_model = Column(String(50))  # 使用的模型
    ai_summary_at = Column(DateTime)
    
    # 元数据
    entry_count = Column(Integer, default=0)  # 条目数量
    word_count = Column(Integer, default=0)   # 字数统计
    
    # 合并相关
    merged_at = Column(DateTime)
    merged_by = Column(String(50))  # 'cron', 'manual', 'api'
    
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("UTC")))
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("UTC")), 
                        onupdate=lambda: datetime.now(ZoneInfo("UTC")))
    
    # 关系
    user = relationship("User", back_populates="journals")
    entries = relationship("Entry", back_populates="journal", order_by="Entry.created_at")
    
    # 复合索引
    __table_args__ = (
        Index('idx_user_date', 'user_id', 'date', unique=True),
        Index('idx_status_merge', 'status', 'date'),
    )


class Entry(Base):
    """
    条目表 - 单条记录（来自各数据源）
    
    设计说明：
    - 支持多种数据源统一存储
    - content 存储主要内容
    - metadata 存储数据源特定的额外信息
    """
    __tablename__ = "entries"
    
    id = Column(Integer, primary_key=True)
    journal_id = Column(Integer, ForeignKey("journals.id"), nullable=False, index=True)
    
    # 数据来源
    source_type = Column(Enum(EntrySourceType), nullable=False, index=True)
    source_id = Column(String(255), index=True)  # 数据源唯一ID (如 Telegram message_id)
    
    # 内容类型
    content_type = Column(Enum(EntryContentType), nullable=False)
    
    # 内容
    content = Column(Text)  # 纯文本内容或 Markdown
    raw_content = Column(Text)  # 原始内容（用于调试和重处理）
    
    # 元数据 (JSON 格式，灵活存储各源特定字段)
    metadata = Column(JSON, default={})
    # 示例元数据：
    # Telegram: {"message_id": 123, "chat_id": 456, "caption": "..."}
    # Douban: {"item_id": "12345", "rating": 5, "title": "..."}
    # Readwise: {"article_id": "abc", "url": "...", "highlights": [...]}
    # Strava: {"activity_id": 123, "distance": 5000, "duration": 1800}
    
    # 标签 (冗余存储方便查询)
    tags = Column(JSON, default=[])  # ["读书", "运动"]
    
    # 排序权重（控制条目在日记中的显示顺序）
    sort_order = Column(Integer, default=0)
    
    # 时区相关
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("UTC")))
    source_created_at = Column(DateTime, index=True)  # 数据源创建时间
    timezone = Column(String(50), default="Asia/Shanghai")
    
    # 去重相关
    content_hash = Column(String(64), index=True)  # SHA256(content) 用于快速去重
    
    # 关系
    journal = relationship("Journal", back_populates="entries")
    media_files = relationship("MediaFile", back_populates="entry")
    
    # 索引
    __table_args__ = (
        Index('idx_source_unique', 'source_type', 'source_id', unique=True),
        Index('idx_journal_order', 'journal_id', 'sort_order'),
    )


class MediaFile(Base):
    """媒体文件表 - 图片、音频等"""
    __tablename__ = "media_files"
    
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("entries.id"), nullable=False, index=True)
    
    # 文件信息
    original_filename = Column(String(500))
    stored_filename = Column(String(500))  # 本地或对象存储路径
    file_type = Column(String(50))  # image/jpeg, image/png, etc.
    file_size = Column(Integer)  # bytes
    
    # GitHub 存储信息
    github_path = Column(String(500))  # content/images/2024/02/12/xxx.jpg
    github_url = Column(String(500))  # raw.githubusercontent.com/...
    github_sha = Column(String(100))  # GitHub blob sha
    
    # Telegram 源信息
    telegram_file_id = Column(String(255))
    telegram_file_unique_id = Column(String(255))
    
    # 图片元数据
    width = Column(Integer)
    height = Column(Integer)
    
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("UTC")))
    
    # 关系
    entry = relationship("Entry", back_populates="media_files")


class SyncConfig(Base):
    """
    数据源同步配置表
    
    每个用户每个数据源一条配置
    """
    __tablename__ = "sync_configs"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    source_type = Column(Enum(EntrySourceType), nullable=False)
    
    # 认证信息 (加密存储)
    credentials = Column(JSON)  # {"token": "xxx", "refresh_token": "yyy"}
    
    # 同步设置
    sync_enabled = Column(Boolean, default=True)
    sync_schedule = Column(String(50), default="0 */6 * * *")  # cron 表达式
    sync_direction = Column(String(20), default="pull")  # pull, push, bidirectional
    
    # 增量同步标记
    last_sync_cursor = Column(String(500))  # 各源特定的游标
    last_sync_at = Column(DateTime)
    last_sync_status = Column(String(50))  # success, failed, partial
    last_sync_error = Column(Text)
    
    # 自定义配置
    config = Column(JSON, default={})
    # Douban: {"user_id": "xxx", "sync_types": ["movie", "book", "music"]}
    # Readwise: {"sync_highlights": true, "sync_articles": true}
    # Strava: {"activity_types": ["Run", "Ride"], "sync_private": false}
    
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("UTC")))
    updated_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("UTC")), 
                        onupdate=lambda: datetime.now(ZoneInfo("UTC")))
    
    # 关系
    user = relationship("User", back_populates="sync_configs")
    
    # 唯一约束：每个用户每个数据源一条配置
    __table_args__ = (
        Index('idx_user_source', 'user_id', 'source_type', unique=True),
    )


class SyncTask(Base):
    """同步任务表 - 记录每次同步执行"""
    __tablename__ = "sync_tasks"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    sync_config_id = Column(Integer, ForeignKey("sync_configs.id"))
    source_type = Column(Enum(EntrySourceType), nullable=False)
    
    status = Column(String(50), default="pending")  # pending, running, success, failed
    
    # 执行信息
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    # 同步结果统计
    items_found = Column(Integer, default=0)
    items_added = Column(Integer, default=0)
    items_skipped = Column(Integer, default=0)  # 重复数据
    items_failed = Column(Integer, default=0)
    
    # 错误信息
    error_message = Column(Text)
    
    # 详细日志
    logs = Column(JSON, default=[])
    
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("UTC")))


class WeeklyReport(Base):
    """周报表 - AI 生成的周报"""
    __tablename__ = "weekly_reports"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # 周期
    year = Column(Integer, nullable=False)
    week_number = Column(Integer, nullable=False)  # ISO week number
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    
    # 统计
    total_entries = Column(Integer, default=0)
    total_words = Column(Integer, default=0)
    source_breakdown = Column(JSON, default={})  # {"telegram": 10, "douban": 5}
    
    # AI 内容
    ai_summary = Column(Text)
    ai_highlights = Column(JSON, default=[])  # 本周亮点
    ai_recommendations = Column(Text)
    
    # GitHub
    github_issue_no = Column(Integer)
    github_issue_url = Column(String(500))
    
    created_at = Column(DateTime, default=lambda: datetime.now(ZoneInfo("UTC")))
    generated_at = Column(DateTime)
    
    __table_args__ = (
        Index('idx_user_week', 'user_id', 'year', 'week_number', unique=True),
    )


# ============================================================================
# 数据库初始化
# ============================================================================

def init_db(db_url: str = "sqlite:///munin.db"):
    """初始化数据库"""
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session
```

### 2.3 关键查询示例

```python
# 查询某用户某日的日记及所有条目
journal = session.query(Journal).filter(
    Journal.user_id == user_id,
    func.date(Journal.date) == date(2024, 2, 12)
).options(
    joinedload(Journal.entries).joinedload(Entry.media_files)
).first()

# 查询待合并的日记（跨天后）
pending_journals = session.query(Journal).filter(
    Journal.status == JournalStatus.COLLECTING,
    func.date(Journal.date) < func.date(func.now())  # 日期小于今天
).all()

# 去重查询 - 检查某条目是否已存在
existing = session.query(Entry).filter(
    Entry.source_type == EntrySourceType.DOUBAN,
    Entry.source_id == douban_item_id
).first()

# 按数据源统计
stats = session.query(
    Entry.source_type,
    func.count(Entry.id).label('count')
).filter(
    Entry.created_at >= start_date,
    Entry.created_at < end_date
).group_by(Entry.source_type).all()
```

---

## 3. 多数据源集成方案

### 3.1 数据源接入策略总览

| 数据源 | API 状态 | 接入方式 | 优先级 | 难度 |
|--------|----------|----------|--------|------|
| **Telegram** | ✅ 官方 API | python-telegram-bot | P0 | 低 |
| **Readwise** | ✅ 官方 API | REST API + OAuth | P1 | 低 |
| **Strava** | ✅ 官方 API | OAuth2 + REST API | P1 | 中 |
| **Douban** | ❌ 已关闭 | 爬虫 / 第三方 RSS | P2 | 高 |
| **Apple Health** | ⚠️ 受限 | 导出文件 / HealthKit | P2 | 高 |

### 3.2 豆瓣集成方案（关键挑战）

**现状分析**：
- 豆瓣官方 API 于 2020 年关闭
- 公开页面需要登录才能访问完整内容
- 有反爬机制

**可行方案对比**：

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **RSS 订阅** | 稳定、无需爬虫 | 需要豆伴等第三方服务 | ⭐⭐⭐⭐ |
| **浏览器插件** | 直接从页面提取 | 需要用户手动操作 | ⭐⭐⭐ |
| **Playwright 爬虫** | 数据完整 | 需要维护登录态，不稳定 | ⭐⭐ |
| **豆瓣同步助手** | 官方支持 | 需要安装独立应用 | ⭐⭐⭐⭐ |

**推荐实现**：

```python
# adapters/douban/rss_adapter.py
"""
豆瓣 RSS 适配器

依赖豆伴(doufen)等服务生成的 RSS Feed
用户需要提供 RSS URL
"""

import feedparser
from datetime import datetime
from typing import List, Dict

class DoubanRSSAdapter:
    """豆瓣 RSS 适配器"""
    
    SUPPORTED_TYPES = ['movie', 'book', 'music']
    
    def __init__(self, rss_url: str):
        self.rss_url = rss_url
    
    def fetch_recent_items(self, since: datetime = None) -> List[Dict]:
        """获取最近的标记"""
        feed = feedparser.parse(self.rss_url)
        
        items = []
        for entry in feed.entries:
            # 解析 RSS entry
            item = {
                'source_id': entry.id,
                'title': entry.title,
                'link': entry.link,
                'published': datetime(*entry.published_parsed[:6]),
                'content': entry.get('summary', ''),
                'rating': self._extract_rating(entry),
                'item_type': self._detect_type(entry),
                'tags': [tag.term for tag in entry.get('tags', [])]
            }
            
            if since and item['published'] <= since:
                continue
                
            items.append(item)
        
        return items
    
    def _extract_rating(self, entry) -> int:
        """从内容中提取评分"""
        # RSS 中可能包含评分信息
        content = entry.get('summary', '')
        # 实现评分提取逻辑
        return 0
    
    def _detect_type(self, entry) -> str:
        """检测条目类型（电影/图书/音乐）"""
        # 通过链接或标签判断
        if '/subject/' in entry.link:
            # 进一步判断是哪种类型
            pass
        return 'unknown'


# 备选：浏览器书签小工具 (Bookmarklet)
"""
如果 RSS 不可用，提供浏览器书签工具让用户一键发送当前页面

javascript:(function(){
    var data = {
        title: document.title,
        url: window.location.href,
        type: window.location.pathname.includes('/movie/') ? 'movie' : 
              window.location.pathname.includes('/book/') ? 'book' : 'music'
    };
    fetch('https://munin-api.example.com/webhook/douban', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    });
})();
"""
```

### 3.3 Readwise 集成

```python
# adapters/readwise/client.py
"""
Readwise 官方 API 客户端

文档: https://readwise.io/api_deets
"""

import requests
from datetime import datetime
from typing import Iterator, Dict, List

class ReadwiseClient:
    """Readwise API 客户端"""
    
    BASE_URL = "https://readwise.io/api/v2"
    
    def __init__(self, token: str):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Token {token}"
        })
    
    def get_books(self, updated_after: datetime = None) -> Iterator[Dict]:
        """获取书摘列表"""
        url = f"{self.BASE_URL}/books/"
        params = {}
        if updated_after:
            params['updated__gt'] = updated_after.isoformat()
        
        while url:
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            for book in data['results']:
                yield book
            
            url = data.get('next')
            params = {}  # 后续请求使用完整 URL
    
    def get_highlights(self, book_id: str = None, updated_after: datetime = None) -> Iterator[Dict]:
        """获取高亮内容"""
        url = f"{self.BASE_URL}/highlights/"
        params = {}
        if book_id:
            params['book_id'] = book_id
        if updated_after:
            params['updated__gt'] = updated_after.isoformat()
        
        while url:
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            for highlight in data['results']:
                yield highlight
            
            url = data.get('next')
    
    def sync_to_entries(self, since: datetime = None) -> List[Dict]:
        """
        同步 Readwise 数据为 Entry 格式
        
        策略：
        1. 每天的文章作为一个 Entry
        2. 当天的高亮聚合到对应文章中
        3. 书摘单独成 Entry
        """
        entries = []
        
        for book in self.get_books(updated_after=since):
            # 获取该书的高亮
            highlights = list(self.get_highlights(book_id=book['id'], updated_after=since))
            
            if highlights:
                entry = {
                    'source_type': 'readwise',
                    'source_id': book['id'],
                    'content_type': 'readwise_article',
                    'title': book['title'],
                    'author': book.get('author'),
                    'url': book.get('source_url'),
                    'content': self._format_highlights(highlights),
                    'metadata': {
                        'category': book.get('category'),  # books, articles, tweets, etc.
                        'num_highlights': len(highlights),
                        'last_highlight_at': book.get('last_highlight_at')
                    }
                }
                entries.append(entry)
        
        return entries
    
    def _format_highlights(self, highlights: List[Dict]) -> str:
        """格式化高亮内容为 Markdown"""
        parts = []
        for h in highlights:
            parts.append(f"> {h['text']}")
            if h.get('note'):
                parts.append(f"> \n> 💭 {h['note']}")
            parts.append("")
        return "\n".join(parts)


# OAuth 授权流程 (首次使用)
"""
Readwise 使用 API Token 而非 OAuth2，获取方式：
1. 用户登录 https://readwise.io/access_token
2. 复制 Token
3. 在 Munin 配置中粘贴
"""
```

### 3.4 Apple Health 集成

```python
# adapters/apple_health/parser.py
"""
Apple Health 数据解析器

Apple Health 不支持直接 API，需要通过以下方式：
1. 用户导出 Health 数据（通过 Health App）
2. 上传到 Munin
3. 解析 export.xml

替代方案：使用第三方同步工具如 Health Auto Export
"""

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Dict
import zipfile

class AppleHealthParser:
    """Apple Health 导出文件解析器"""
    
    def __init__(self, export_path: Path):
        self.export_path = export_path
    
    def parse(self) -> List[Dict]:
        """解析导出文件"""
        # export.xml 通常在导出 zip 中
        if self.export_path.suffix == '.zip':
            xml_content = self._extract_xml_from_zip()
        else:
            xml_content = self.export_path.read_text()
        
        root = ET.fromstring(xml_content)
        
        entries = []
        
        # 解析运动记录
        for workout in root.findall('.//Workout'):
            entry = self._parse_workout(workout)
            if entry:
                entries.append(entry)
        
        # 解析健康指标
        for record in root.findall('.//Record[@type="HKQuantityTypeIdentifierHeartRate"]'):
            # 可选择性记录心率数据
            pass
        
        return entries
    
    def _parse_workout(self, workout: ET.Element) -> Dict:
        """解析单次运动"""
        workout_type = workout.get('workoutActivityType', '')
        
        # 映射 Apple Health 类型到我们的类型
        type_mapping = {
            'HKWorkoutActivityTypeRunning': 'run',
            'HKWorkoutActivityTypeCycling': 'ride',
            'HKWorkoutActivityTypeWalking': 'walk',
            'HKWorkoutActivityTypeSwimming': 'swim',
            'HKWorkoutActivityTypeYoga': 'yoga',
        }
        
        return {
            'source_type': 'apple_health',
            'source_id': workout.get('UUID'),
            'content_type': 'health_workout',
            'activity_type': type_mapping.get(workout_type, 'other'),
            'start_time': datetime.fromisoformat(workout.get('startDate')),
            'end_time': datetime.fromisoformat(workout.get('endDate')),
            'duration': float(workout.get('duration', 0)),  # 分钟
            'distance': self._get_workout_stat(workout, 'Distance'),  # 公里
            'energy_burned': self._get_workout_stat(workout, 'Energy'),  # 卡路里
            'metadata': {
                'raw_type': workout_type,
                'source': workout.get('sourceName')
            }
        }
    
    def _get_workout_stat(self, workout: ET.Element, stat_type: str) -> float:
        """获取运动统计数据"""
        for stat in workout.findall(f'.//WorkoutStatistics[@type="HKQuantityTypeIdentifier{stat_type}"]'):
            return float(stat.get('sum', 0))
        return 0.0


# adapters/apple_health/auto_export.py
"""
使用 Health Auto Export 的 webhook 功能实现自动同步

Health Auto Export 是一款 iOS App，可以：
1. 自动监控 Apple Health 数据变化
2. 通过 webhook 发送数据
3. 支持自定义数据格式

配置步骤：
1. 安装 Health Auto Export App
2. 配置 webhook URL 指向 Munin API
3. 选择要同步的数据类型
"""

from fastapi import APIRouter, Request

router = APIRouter()

@router.post("/webhook/apple-health")
async def apple_health_webhook(request: Request):
    """接收 Health Auto Export 推送的数据"""
    data = await request.json()
    
    # Health Auto Export 发送的数据格式
    workout = {
        'source_type': 'apple_health',
        'source_id': data.get('uuid'),
        'activity_type': data.get('activity_type'),
        'start_time': data.get('start_time'),
        'duration': data.get('duration'),
        'distance': data.get('distance'),
        'energy_burned': data.get('calories'),
    }
    
    # 保存到数据库
    await save_entry(workout)
    
    return {"status": "ok"}
```

### 3.5 Strava 集成

```python
# adapters/strava/client.py
"""
Strava API 客户端

文档: https://developers.strava.com/docs/
"""

import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional

class StravaClient:
    """Strava API 客户端"""
    
    BASE_URL = "https://www.strava.com/api/v3"
    
    def __init__(self, access_token: str, refresh_token: str = None, 
                 client_id: str = None, client_secret: str = None):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = requests.Session()
        self._update_auth_header()
    
    def _update_auth_header(self):
        self.session.headers.update({
            "Authorization": f"Bearer {self.access_token}"
        })
    
    def refresh_access_token(self) -> bool:
        """刷新 access token"""
        if not all([self.refresh_token, self.client_id, self.client_secret]):
            return False
        
        resp = requests.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token"
            }
        )
        
        if resp.status_code == 200:
            data = resp.json()
            self.access_token = data['access_token']
            self.refresh_token = data['refresh_token']
            self._update_auth_header()
            return True
        return False
    
    def get_activities(self, after: datetime = None, before: datetime = None,
                       per_page: int = 30) -> List[Dict]:
        """获取活动列表"""
        url = f"{self.BASE_URL}/athlete/activities"
        params = {"per_page": per_page}
        
        if after:
            params['after'] = int(after.timestamp())
        if before:
            params['before'] = int(before.timestamp())
        
        resp = self.session.get(url, params=params)
        
        if resp.status_code == 401 and self.refresh_access_token():
            resp = self.session.get(url, params=params)
        
        resp.raise_for_status()
        return resp.json()
    
    def get_activity(self, activity_id: int) -> Dict:
        """获取活动详情"""
        url = f"{self.BASE_URL}/activities/{activity_id}"
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.json()
    
    def activity_to_entry(self, activity: Dict) -> Dict:
        """转换 Strava 活动为 Entry 格式"""
        return {
            'source_type': 'strava',
            'source_id': str(activity['id']),
            'content_type': 'strava_activity',
            'title': activity.get('name', 'Untitled Activity'),
            'activity_type': activity.get('sport_type', activity.get('type')),
            'start_time': datetime.fromisoformat(activity['start_date_local']),
            'duration': activity.get('elapsed_time', 0) / 60,  # 转为分钟
            'distance': (activity.get('distance', 0) / 1000) if activity.get('distance') else None,  # 转为公里
            'elevation_gain': activity.get('total_elevation_gain'),  # 米
            'average_speed': activity.get('average_speed'),  # m/s
            'max_speed': activity.get('max_speed'),
            'average_heartrate': activity.get('average_heartrate'),
            'max_heartrate': activity.get('max_heartrate'),
            'calories': activity.get('calories'),
            'description': activity.get('description', ''),
            'metadata': {
                'gear_id': activity.get('gear_id'),
                'polyline': activity.get('map', {}).get('summary_polyline'),
                'has_heartrate': activity.get('has_heartrate'),
                'achievement_count': activity.get('achievement_count'),
                'kudos_count': activity.get('kudos_count'),
            }
        }


# OAuth 授权流程
"""
Strava OAuth 流程：

1. 引导用户访问授权 URL:
   https://www.strava.com/oauth/authorize?
     client_id=YOUR_CLIENT_ID&
     response_type=code&
     redirect_uri=YOUR_REDIRECT_URI&
     approval_prompt=force&
     scope=read,activity:read

2. 用户授权后，Strava 重定向到 callback URL 并附带 code

3. 使用 code 换取 access_token:
   POST https://www.strava.com/oauth/token
   {
     "client_id": "YOUR_CLIENT_ID",
     "client_secret": "YOUR_CLIENT_SECRET",
     "code": "AUTHORIZATION_CODE",
     "grant_type": "authorization_code"
   }

4. 返回包含 access_token 和 refresh_token
"""

# FastAPI OAuth 回调端点示例
@router.get("/oauth/strava/callback")
async def strava_oauth_callback(code: str, state: str = None):
    """处理 Strava OAuth 回调"""
    # 验证 state 防止 CSRF
    
    # 换取 token
    resp = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": settings.STRAVA_CLIENT_ID,
            "client_secret": settings.STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code"
        }
    )
    
    data = resp.json()
    
    # 保存到用户配置
    await save_sync_config(
        user_id=state,
        source_type='strava',
        credentials={
            'access_token': data['access_token'],
            'refresh_token': data['refresh_token'],
            'expires_at': data['expires_at']
        }
    )
    
    return {"status": "success", "message": "Strava 授权成功"}
```

---

## 4. 同步机制设计

### 4.1 定时任务 vs Webhook 策略

| 数据源 | 推荐方式 | 原因 | 频率 |
|--------|----------|------|------|
| Telegram | Webhook/Long Polling | 实时性要求高 | 实时 |
| Readwise | 定时任务 | API 调用有频率限制 | 每6小时 |
| Strava | 定时任务 + Webhook | 支持 webhook 但需配置 | 每3小时 + 实时 |
| Apple Health | Webhook (Health Auto Export) | 无官方 API | 实时 |
| Douban | 定时任务 | RSS 同步 | 每12小时 |

### 4.2 同步调度器实现

```python
# scheduler/sync_scheduler.py
"""
统一的数据同步调度器

使用 APScheduler 实现定时任务调度
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import asyncio
from datetime import datetime
from typing import Dict, Type

class SyncScheduler:
    """数据同步调度器"""
    
    # 数据源适配器映射
    ADAPTERS: Dict[str, Type] = {
        'readwise': ReadwiseAdapter,
        'strava': StravaAdapter,
        'douban': DoubanRSSAdapter,
    }
    
    def __init__(self, db_session):
        self.db = db_session
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_listener(
            self._on_job_executed, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )
    
    def start(self):
        """启动调度器"""
        self._load_user_jobs()
        self.scheduler.start()
    
    def _load_user_jobs(self):
        """为每个启用的同步配置加载任务"""
        configs = self.db.query(SyncConfig).filter(
            SyncConfig.sync_enabled == True
        ).all()
        
        for config in configs:
            self._schedule_sync(config)
    
    def _schedule_sync(self, config: SyncConfig):
        """调度单个同步任务"""
        job_id = f"sync_{config.user_id}_{config.source_type}"
        
        # 如果任务已存在，先移除
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        
        # 使用用户配置的 cron 表达式
        trigger = CronTrigger.from_crontab(config.sync_schedule)
        
        self.scheduler.add_job(
            func=self._run_sync,
            trigger=trigger,
            id=job_id,
            args=[config.user_id, config.source_type],
            replace_existing=True,
            misfire_grace_time=3600  # 1小时容错
        )
    
    async def _run_sync(self, user_id: int, source_type: str):
        """执行同步任务"""
        # 创建任务记录
        task = SyncTask(
            user_id=user_id,
            source_type=source_type,
            status='running',
            started_at=datetime.utcnow()
        )
        self.db.add(task)
        self.db.commit()
        
        try:
            # 获取适配器
            adapter_class = self.ADAPTERS.get(source_type)
            if not adapter_class:
                raise ValueError(f"Unknown source type: {source_type}")
            
            # 加载用户配置
            config = self.db.query(SyncConfig).filter(
                SyncConfig.user_id == user_id,
                SyncConfig.source_type == source_type
            ).first()
            
            adapter = adapter_class(**config.credentials)
            
            # 执行同步
            since = config.last_sync_at
            entries = await adapter.sync(since)
            
            # 保存条目
            added = 0
            skipped = 0
            for entry_data in entries:
                # 去重检查
                existing = self.db.query(Entry).filter(
                    Entry.source_type == source_type,
                    Entry.source_id == entry_data['source_id']
                ).first()
                
                if existing:
                    skipped += 1
                    continue
                
                # 创建 Entry
                entry = Entry(**entry_data, user_id=user_id)
                self.db.add(entry)
                added += 1
            
            # 更新配置状态
            config.last_sync_at = datetime.utcnow()
            config.last_sync_status = 'success'
            
            # 更新任务记录
            task.status = 'success'
            task.items_added = added
            task.items_skipped = skipped
            task.completed_at = datetime.utcnow()
            
            self.db.commit()
            
        except Exception as e:
            # 记录错误
            task.status = 'failed'
            task.error_message = str(e)
            task.completed_at = datetime.utcnow()
            
            config.last_sync_status = 'failed'
            config.last_sync_error = str(e)
            
            self.db.commit()
            raise
    
    def _on_job_executed(self, event):
        """任务执行回调"""
        if event.exception:
            print(f"Job {event.job_id} failed: {event.exception}")
        else:
            print(f"Job {event.job_id} completed successfully")


# ============================================================================
# 跨天合并触发器 (核心功能)
# ============================================================================

class DailyMergeScheduler:
    """
    跨天自动合并调度器
    
    设计要点：
    1. 每天 00:00 触发前一天的合并
    2. 处理时区问题 - 按用户时区判断日期
    3. 幂等性 - 重复执行不会重复创建 Issue
    """
    
    def __init__(self, db_session, github_client_factory):
        self.db = db_session
        self.github_factory = github_client_factory
        self.scheduler = AsyncIOScheduler()
    
    def start(self):
        """启动调度器"""
        # 每分钟检查一次是否有需要合并的日记
        self.scheduler.add_job(
            self._check_and_merge,
            trigger='cron',
            minute='*/5',  # 每5分钟检查
            id='daily_merge_checker'
        )
        
        self.scheduler.start()
    
    async def _check_and_merge(self):
        """检查并执行合并"""
        # 获取所有用户
        users = self.db.query(User).all()
        
        for user in users:
            await self._merge_user_pending_journals(user)
    
    async def _merge_user_pending_journals(self, user: User):
        """合并用户的待处理日记"""
        from zoneinfo import ZoneInfo
        
        # 获取用户当前时区的日期
        user_tz = ZoneInfo(user.timezone)
        now_user = datetime.now(user_tz)
        today = now_user.date()
        
        # 查找 COLLECTING 状态且日期早于今天的日记
        pending_journals = self.db.query(Journal).filter(
            Journal.user_id == user.id,
            Journal.status == JournalStatus.COLLECTING,
            func.date(Journal.date) < today
        ).all()
        
        for journal in pending_journals:
            await self._merge_journal(journal)
    
    async def _merge_journal(self, journal: Journal):
        """合并单篇日记"""
        # 状态变更为 PENDING_MERGE
        journal.status = JournalStatus.PENDING_MERGE
        self.db.commit()
        
        try:
            # 获取所有条目
            entries = self.db.query(Entry).filter(
                Entry.journal_id == journal.id
            ).order_by(Entry.sort_order, Entry.created_at).all()
            
            if not entries:
                # 空日记，直接标记为已合并
                journal.status = JournalStatus.MERGED
                self.db.commit()
                return
            
            # 生成 Markdown 内容
            markdown = self._generate_journal_markdown(journal, entries)
            
            # 创建 GitHub Issue
            github = self.github_factory(journal.user)
            issue = github.create_issue(
                title=journal.date.strftime("%Y%m%d"),
                body=markdown,
                labels=['journal'] + self._extract_all_tags(entries)
            )
            
            # 更新日记状态
            journal.status = JournalStatus.MERGED
            journal.github_issue_no = issue['number']
            journal.github_issue_url = issue['html_url']
            journal.merged_at = datetime.utcnow()
            journal.merged_by = 'cron'
            
            self.db.commit()
            
        except Exception as e:
            # 回滚状态
            journal.status = JournalStatus.COLLECTING
            self.db.commit()
            raise
    
    def _generate_journal_markdown(self, journal: Journal, entries: List[Entry]) -> str:
        """生成日记 Markdown 内容"""
        parts = []
        
        # 标题
        parts.append(f"# {journal.date.strftime('%Y年%m月%d日')} 日记")
        parts.append("")
        
        # 按数据源分组
        entries_by_source = {}
        for entry in entries:
            source = entry.source_type
            if source not in entries_by_source:
                entries_by_source[source] = []
            entries_by_source[source].append(entry)
        
        # 生成各部分内容
        source_order = [
            EntrySourceType.TELEGRAM,
            EntrySourceType.DOUBAN,
            EntrySourceType.READWISE,
            EntrySourceType.STRAVA,
            EntrySourceType.APPLE_HEALTH,
        ]
        
        for source in source_order:
            if source not in entries_by_source:
                continue
            
            source_entries = entries_by_source[source]
            section = self._generate_source_section(source, source_entries)
            parts.append(section)
        
        # 添加统计信息
        parts.append("---")
        parts.append("")
        parts.append("### 📊 今日统计")
        parts.append(f"- 总条目: {len(entries)}")
        for source, source_entries in entries_by_source.items():
            parts.append(f"- {source.value}: {len(source_entries)}")
        
        return "\n".join(parts)
    
    def _generate_source_section(self, source: EntrySourceType, entries: List[Entry]) -> str:
        """生成某一数据源的 Markdown 章节"""
        source_names = {
            EntrySourceType.TELEGRAM: "📝 随手记",
            EntrySourceType.DOUBAN: "🎬 影音书记录",
            EntrySourceType.READWISE: "📚 今日阅读",
            EntrySourceType.STRAVA: "🏃 运动记录",
            EntrySourceType.APPLE_HEALTH: "💪 健康数据",
        }
        
        parts = []
        parts.append(f"## {source_names.get(source, source.value)}")
        parts.append("")
        
        for entry in entries:
            if entry.content:
                parts.append(entry.content)
                parts.append("")
        
        return "\n".join(parts)
```

### 4.3 数据去重策略

```python
# deduplication/strategies.py
"""
数据去重策略

不同数据源采用不同的去重策略
"""

import hashlib
from typing import Optional
from abc import ABC, abstractmethod

class DeduplicationStrategy(ABC):
    """去重策略基类"""
    
    @abstractmethod
    def generate_key(self, entry_data: dict) -> str:
        """生成去重键"""
        pass


class SourceIdStrategy(DeduplicationStrategy):
    """
    基于数据源 ID 去重
    适用于有稳定唯一 ID 的源：Readwise, Strava, Telegram
    """
    def generate_key(self, entry_data: dict) -> str:
        source_type = entry_data.get('source_type')
        source_id = entry_data.get('source_id')
        return f"{source_type}:{source_id}"


class ContentHashStrategy(DeduplicationStrategy):
    """
    基于内容哈希去重
    适用于内容确定的源：豆瓣、文章摘录
    """
    def generate_key(self, entry_data: dict) -> str:
        content = entry_data.get('content', '')
        # 标准化内容后哈希
        normalized = self._normalize(content)
        hash_value = hashlib.sha256(normalized.encode()).hexdigest()
        return f"hash:{hash_value[:16]}"
    
    def _normalize(self, content: str) -> str:
        """标准化内容（去除空白、转小写等）"""
        return ' '.join(content.lower().split())


class FuzzyMatchStrategy(DeduplicationStrategy):
    """
    模糊匹配去重
    适用于可能有轻微变动的内容
    """
    def __init__(self, threshold: float = 0.9):
        self.threshold = threshold
    
    def generate_key(self, entry_data: dict) -> str:
        # 生成 SimHash 或 MinHash
        # 这里简化处理，实际需要更复杂的实现
        return f"fuzzy:{self._simhash(entry_data.get('content', ''))}"
    
    def _simhash(self, content: str) -> str:
        # 简化的 SimHash 实现
        # 实际应使用专业的模糊匹配库
        import hashlib
        return hashlib.md5(content[:100].encode()).hexdigest()[:8]


# 数据源去重策略映射
DEDUP_STRATEGIES = {
    'telegram': SourceIdStrategy(),
    'readwise': SourceIdStrategy(),
    'strava': SourceIdStrategy(),
    'douban': ContentHashStrategy(),
    'apple_health': SourceIdStrategy(),
}


async def check_duplicate(db_session, entry_data: dict) -> Optional[Entry]:
    """
    检查条目是否重复
    
    优先使用 source_id 精确匹配，
    对于没有 source_id 的，使用内容哈希
    """
    source_type = entry_data.get('source_type')
    strategy = DEDUP_STRATEGIES.get(source_type, ContentHashStrategy())
    
    # 先尝试精确匹配
    source_id = entry_data.get('source_id')
    if source_id:
        existing = db_session.query(Entry).filter(
            Entry.source_type == source_type,
            Entry.source_id == source_id
        ).first()
        if existing:
            return existing
    
    # 再尝试内容哈希
    content_hash = entry_data.get('content_hash')
    if content_hash:
        existing = db_session.query(Entry).filter(
            Entry.source_type == source_type,
            Entry.content_hash == content_hash
        ).first()
        if existing:
            return existing
    
    return None
```

---

## 5. AI 总结实现

### 5.1 AI 总结架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      AI Summary Pipeline                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐    │
│  │   Trigger   │───▶│  Aggregate  │───▶│  Generate       │    │
│  │             │    │   Data      │    │  (LLM API)      │    │
│  └─────────────┘    └─────────────┘    └─────────────────┘    │
│        │                                          │            │
│        │                                          ▼            │
│        │                               ┌─────────────────┐     │
│        │                               │  Post-process   │     │
│        │                               │  - Extract      │     │
│        │                               │    highlights   │     │
│        │                               │  - Format       │     │
│        │                               └─────────────────┘     │
│        │                                          │            │
│        ▼                                          ▼            │
│  ┌─────────────┐                        ┌─────────────────┐    │
│  │  Schedule   │◀───────────────────────│  Store Result   │    │
│  │  Next Run   │                        │  (DB/Issue)     │    │
│  └─────────────┘                        └─────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 实现代码

```python
# ai/summary_generator.py
"""
AI 总结生成器

支持多种 LLM 提供商：
- OpenAI GPT-4
- Anthropic Claude
- Azure OpenAI
- 本地模型 (Ollama)
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime
import json
import openai
from anthropic import Anthropic

class LLMProvider(ABC):
    """LLM 提供商基类"""
    
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI 提供商"""
    
    def __init__(self, api_key: str, model: str = "gpt-4-turbo-preview"):
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = model
    
    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=2000
        )
        
        return response.choices[0].message.content


class AnthropicProvider(LLMProvider):
    """Anthropic Claude 提供商"""
    
    def __init__(self, api_key: str, model: str = "claude-3-sonnet-20240229"):
        self.client = Anthropic(api_key=api_key)
        self.model = model
    
    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.content[0].text


class SummaryGenerator:
    """日记总结生成器"""
    
    SYSTEM_PROMPT = """你是一个个人日记助手，擅长从日常记录中提炼要点、发现模式和洞察。
你需要以温暖、理解的语气总结用户的日记内容，帮助用户回顾和理解自己的一天。
输出必须是有效的 JSON 格式。"""

    DAILY_PROMPT_TEMPLATE = """请总结以下 {date} 的日记内容：

{content}

请按以下 JSON 格式输出总结：
{{
    "overview": "用2-3句话概括今天的主题和情绪",
    "highlights": [
        "今天最重要的3-5个亮点或事件"
    ],
    "categories": {{
        "工作/学习": "相关工作或学习内容的总结",
        "生活": "生活琐事的总结",
        "娱乐": "影视、阅读、运动等娱乐活动的总结",
        "思考": "重要的想法、感悟或反思"
    }},
    "mood": "整体情绪判断（如：积极/平静/疲惫/兴奋等）",
    "tomorrow_suggestion": "基于今天的内容，给明天的一个小建议"
}}

注意：
- 保持客观和温暖的语气
- 突出用户可能忽视的亮点
- 不要过度解读，基于文本内容总结
- 输出必须是有效的 JSON"""

    WEEKLY_PROMPT_TEMPLATE = """请总结以下 {start_date} 至 {end_date} 的周记：

{daily_summaries}

请按以下 JSON 格式输出周报：
{{
    "theme": "本周主题",
    "highlights": ["本周3-5个重要亮点"],
    "patterns": ["发现的行为或情绪模式"],
    "achievements": ["本周成就"],
    "challenges": ["本周挑战或困难"],
    "recommendations": ["下周建议"]
}}
"""

    def __init__(self, provider: LLMProvider):
        self.provider = provider
    
    async def generate_daily_summary(
        self, 
        date: datetime, 
        entries: List[Entry]
    ) -> Dict:
        """生成单日总结"""
        
        # 聚合内容
        content_parts = []
        for i, entry in enumerate(entries, 1):
            source_emoji = {
                'telegram': '📝',
                'douban': '🎬',
                'readwise': '📚',
                'strava': '🏃',
                'apple_health': '💪'
            }.get(entry.source_type.value, '📄')
            
            content_parts.append(f"{source_emoji} 条目 {i} ({entry.source_type.value}):")
            content_parts.append(entry.content or "(无文字内容)")
            content_parts.append("")
        
        prompt = self.DAILY_PROMPT_TEMPLATE.format(
            date=date.strftime("%Y年%m月%d日"),
            content="\n".join(content_parts)
        )
        
        # 生成总结
        response = await self.provider.generate(prompt, self.SYSTEM_PROMPT)
        
        # 解析 JSON
        try:
            # 尝试直接解析
            summary = json.loads(response)
        except json.JSONDecodeError:
            # 尝试从 Markdown 代码块中提取
            summary = self._extract_json_from_markdown(response)
        
        return summary
    
    async def generate_weekly_summary(
        self,
        start_date: datetime,
        end_date: datetime,
        daily_journals: List[Journal]
    ) -> Dict:
        """生成周报"""
        
        # 聚合每日总结
        daily_parts = []
        for journal in daily_journals:
            if journal.ai_summary:
                daily_parts.append(f"{journal.date.strftime('%m月%d日')}:")
                daily_parts.append(journal.ai_summary.get('overview', ''))
                daily_parts.append("")
        
        prompt = self.WEEKLY_PROMPT_TEMPLATE.format(
            start_date=start_date.strftime("%Y年%m月%d日"),
            end_date=end_date.strftime("%Y年%m月%d日"),
            daily_summaries="\n".join(daily_parts)
        )
        
        response = await self.provider.generate(prompt, self.SYSTEM_PROMPT)
        return self._extract_json_from_markdown(response)
    
    def _extract_json_from_markdown(self, text: str) -> Dict:
        """从 Markdown 代码块中提取 JSON"""
        import re
        
        # 匹配 ```json ... ``` 或 ``` ... ```
        patterns = [
            r'```json\s*(\{.*?\})\s*```',
            r'```\s*(\{.*?\})\s*```',
            r'(\{[\s\S]*\})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
        
        # 如果都无法解析，返回原始文本
        return {"raw": text}


# ============================================================================
# 触发机制
# ============================================================================

class AISummaryScheduler:
    """AI 总结调度器"""
    
    def __init__(self, db_session, summary_generator: SummaryGenerator):
        self.db = db_session
        self.generator = summary_generator
        self.scheduler = AsyncIOScheduler()
    
    def start(self):
        """启动调度器"""
        # 每日总结：每天凌晨 0:30 生成前一天总结
        self.scheduler.add_job(
            self._generate_daily_summaries,
            trigger='cron',
            hour=0,
            minute=30,
            id='daily_summary'
        )
        
        # 周报：每周一早上 8:00 生成上周周报
        self.scheduler.add_job(
            self._generate_weekly_reports,
            trigger='cron',
            day_of_week='mon',
            hour=8,
            minute=0,
            id='weekly_report'
        )
        
        self.scheduler.start()
    
    async def _generate_daily_summaries(self):
        """生成每日总结"""
        yesterday = datetime.now().date() - timedelta(days=1)
        
        # 获取昨天已合并但未生成总结的日记
        journals = self.db.query(Journal).filter(
            Journal.status == JournalStatus.MERGED,
            func.date(Journal.date) == yesterday,
            Journal.ai_summary.is_(None)
        ).all()
        
        for journal in journals:
            try:
                # 获取条目
                entries = self.db.query(Entry).filter(
                    Entry.journal_id == journal.id
                ).all()
                
                # 生成总结
                summary = await self.generator.generate_daily_summary(
                    journal.date, entries
                )
                
                # 保存到日记
                journal.ai_summary = summary
                journal.ai_summary_model = "gpt-4-turbo"
                journal.ai_summary_at = datetime.utcnow()
                
                self.db.commit()
                
                # 如果启用了 GitHub Issue 更新，更新 Issue 内容
                if journal.github_issue_no:
                    await self._update_github_issue_with_summary(journal)
                
            except Exception as e:
                print(f"Failed to generate summary for journal {journal.id}: {e}")
    
    async def _update_github_issue_with_summary(self, journal: Journal):
        """更新 GitHub Issue 添加 AI 总结"""
        # 在 Issue 内容末尾添加 AI 总结
        summary = journal.ai_summary
        if not summary:
            return
        
        # 构建总结 Markdown
        summary_md = f"""

---

## 🤖 AI 总结

### 今日概览
{summary.get('overview', '')}

### 亮点
{chr(10).join(['- ' + h for h in summary.get('highlights', [])])}

### 情绪
{summary.get('mood', '')}

### 明日建议
{summary.get('tomorrow_suggestion', '')}

*Generated by {journal.ai_summary_model} at {journal.ai_summary_at}*
"""
        
        # 更新 Issue（追加到原有内容）
        github = GitHubClient(journal.user)
        
        # 获取当前 Issue 内容
        current_body = github.get_issue_body(journal.github_issue_no)
        
        # 追加总结
        new_body = current_body + summary_md
        
        github.update_issue_body(journal.github_issue_no, new_body)
```

---

## 6. GitHub Issue 格式演进

### 6.1 多源数据展示格式

```markdown
<!-- 生成的日记 Issue 格式示例 -->

# 2024年02月12日 日记

<!-- 使用 HTML 注释存储元数据，不影响渲染 -->
<!-- 
metadata: {
    "date": "2024-02-12",
    "entry_count": 5,
    "sources": ["telegram", "douban", "readwise"],
    "ai_summary": true
}
-->

---

## 📝 随手记

早晨去公园散步，天气真好 #生活 #随想

![晨跑照片](/content/images/2024/02/12/photo_074512_abc123.jpg)

---

## 🎬 影音书记录

### 《沙丘2》
- 评分: ⭐⭐⭐⭐⭐
- 观影时间: 2024-02-12 19:30
- 标签: #电影 #科幻

视听盛宴，比第一部更精彩。赞达亚的表演让人印象深刻。

### 《置身事内》
- 评分: ⭐⭐⭐⭐
- 阅读进度: 读完
- 标签: #读书 #经济

理解中国政府与经济发展的入门好书，通俗易懂。

---

## 📚 今日阅读

### [文章标题](https://example.com/article)
- 来源: 微信公众号 / 博客 / 新闻
- 阅读时长: 5分钟

> 精彩摘录内容...
> 
> 💭 我的想法：这个观点很有意思

---

## 🏃 运动记录

### 傍晚跑步
- 类型: 跑步
- 距离: 5.23 km
- 用时: 28:45
- 配速: 5:30 /km
- 消耗: 342 kcal
- 平均心率: 152 bpm

<!-- Strava 活动嵌入 -->
![Strava](https://strava.com/activities/12345678/embed)

---

## 💪 健康数据

- 步数: 8,456
- 活跃热量: 456 kcal
- 静息心率: 62 bpm

---

## 🤖 AI 总结

### 今日概览
今天是充实的一天，完成了运动目标，看完了两本/部电影，保持了良好的阅读习惯。

### 亮点
- 晨跑享受了好天气
- 看完期待已久的《沙丘2》
- 完成了一本经济类书籍的阅读

### 情绪
积极、充实

### 明日建议
可以尝试把今天的读书心得记录下来，形成一篇完整的读书笔记。

*Generated by GPT-4 at 2024-02-13T00:30:00Z*

---

## 📊 今日统计

| 数据源 | 条目数 | 占比 |
|--------|--------|------|
| Telegram | 2 | 40% |
| 豆瓣 | 2 | 40% |
| Readwise | 1 | 20% |

**总计: 5 条目，约 1,250 字**
```

### 6.2 标签策略

```python
# labels/strategy.py

"""
GitHub Issue 标签策略

层级结构：
- 类型标签 (type:*)
- 数据源标签 (source:*)
- 内容标签 (用户自定义)
- 状态标签 (status:*)
- 周期标签 (period:*)
"""

DEFAULT_LABELS = {
    # 类型标签
    'type': [
        'journal',           # 日记条目
        'weekly-report',     # 周报
        'monthly-report',    # 月报
        'summary',           # 总结
    ],
    
    # 数据源标签
    'source': [
        'source:telegram',
        'source:douban',
        'source:readwise',
        'source:strava',
        'source:apple-health',
    ],
    
    # 状态标签
    'status': [
        'status:collecting',    # 收集中
        'status:merged',        # 已合并
        'status:ai-summary',    # 已生成 AI 总结
        'status:published',     # 已发布到博客
    ],
    
    # 周期标签（可选，用于快速筛选）
    'period': [
        '2024',
        '2024-Q1',
        '2024-02',
        'week-07',
    ]
}


def generate_labels(journal: Journal, entries: List[Entry]) -> List[str]:
    """为日记生成标签"""
    labels = ['journal']
    
    # 添加数据源标签
    sources = {e.source_type.value for e in entries}
    for source in sources:
        labels.append(f'source:{source}')
    
    # 添加内容标签（从用户标签中聚合）
    all_tags = set()
    for entry in entries:
        all_tags.update(entry.tags or [])
    labels.extend(all_tags)
    
    # 添加状态标签
    labels.append('status:merged')
    
    # 添加周期标签
    labels.append(str(journal.date.year))
    labels.append(f"{journal.date.year}-{journal.date.month:02d}")
    
    return labels
```

---

## 7. 部署和运维

### 7.1 服务架构

```yaml
# docker-compose.yml
version: '3.8'

services:
  # 主应用
  munin-api:
    build: .
    container_name: munin-api
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=sqlite:///data/munin.db
      - REDIS_URL=redis://redis:6379
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - GITHUB_TOKEN=${GITHUB_TOKEN}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    depends_on:
      - redis
    networks:
      - munin-network

  # 后台任务处理器
  munin-worker:
    build: .
    container_name: munin-worker
    command: celery -A tasks worker --loglevel=info
    restart: unless-stopped
    environment:
      - DATABASE_URL=sqlite:///data/munin.db
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    depends_on:
      - redis
      - munin-api
    networks:
      - munin-network

  # 定时任务调度器
  munin-scheduler:
    build: .
    container_name: munin-scheduler
    command: celery -A tasks beat --loglevel=info
    restart: unless-stopped
    environment:
      - DATABASE_URL=sqlite:///data/munin.db
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./data:/app/data
    depends_on:
      - redis
    networks:
      - munin-network

  # Redis (缓存 + 消息队列)
  redis:
    image: redis:7-alpine
    container_name: munin-redis
    restart: unless-stopped
    volumes:
      - redis-data:/data
    networks:
      - munin-network

  # 可选：Web 管理界面
  munin-web:
    build: ./web
    container_name: munin-web
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      - API_URL=http://munin-api:8000
    depends_on:
      - munin-api
    networks:
      - munin-network

volumes:
  redis-data:

networks:
  munin-network:
    driver: bridge
```

### 7.2 监控和告警

```python
# monitoring/health_check.py
"""
健康检查和监控
"""

from fastapi import FastAPI, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import psutil
import time

app = FastAPI()

# Prometheus 指标
journal_entries_total = Counter(
    'munin_journal_entries_total',
    'Total number of journal entries',
    ['source_type']
)

sync_duration = Histogram(
    'munin_sync_duration_seconds',
    'Time spent syncing data',
    ['source_type']
)

merge_failures_total = Counter(
    'munin_merge_failures_total',
    'Total number of merge failures'
)

@app.get("/health")
async def health_check():
    """健康检查端点"""
    checks = {
        "database": await check_database(),
        "redis": await check_redis(),
        "github_api": await check_github_api(),
        "telegram_bot": await check_telegram_bot(),
    }
    
    healthy = all(checks.values())
    
    return {
        "status": "healthy" if healthy else "unhealthy",
        "checks": checks,
        "timestamp": time.time()
    }

@app.get("/metrics")
async def metrics():
    """Prometheus 指标端点"""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


# 告警规则 (Prometheus AlertManager)
ALERT_RULES = """
groups:
- name: munin-alerts
  rules:
  - alert: MuninBotDown
    expr: up{job="munin-api"} == 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Munin Bot is down"
      description: "Munin API has been down for more than 5 minutes"

  - alert: JournalMergeFailures
    expr: rate(munin_merge_failures_total[5m]) > 0.1
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "High rate of journal merge failures"
      description: "More than 10% of journal merges are failing"

  - alert: SyncLag
    expr: time() - munin_last_sync_timestamp > 3600
    for: 15m
    labels:
      severity: warning
    annotations:
      summary: "Data sync is lagging"
      description: "Last successful sync was more than 1 hour ago"
"""

# 备份脚本
BACKUP_SCRIPT = """#!/bin/bash
# backup.sh - 数据备份脚本

BACKUP_DIR="/backups/munin"
DATE=$(date +%Y%m%d_%H%M%S)

# 创建备份目录
mkdir -p $BACKUP_DIR

# 备份数据库
sqlite3 /app/data/munin.db ".backup '$BACKUP_DIR/munin_$DATE.db'"

# 压缩备份
gzip $BACKUP_DIR/munin_$DATE.db

# 保留最近30天的备份
find $BACKUP_DIR -name "munin_*.db.gz" -mtime +30 -delete

# 可选：上传到云存储
# aws s3 cp $BACKUP_DIR/munin_$DATE.db.gz s3://my-backup-bucket/munin/

echo "Backup completed: munin_$DATE.db.gz"
"""
```

---

## 8. 代码实现建议

### 8.1 项目结构

```
/Users/zhengcc/developer/Munin/
├── bot/                          # Telegram Bot 核心
│   ├── __init__.py
│   ├── main.py                   # 入口
│   ├── config.py                 # 配置管理
│   ├── handlers.py               # 消息处理器
│   └── cli.py                    # CLI 工具
│
├── core/                         # 核心服务
│   ├── __init__.py
│   ├── models.py                 # SQLAlchemy 模型
│   ├── database.py               # 数据库连接
│   ├── journal_manager.py        # 日记管理
│   ├── entry_collector.py        # 条目收集
│   └── sync_scheduler.py         # 同步调度
│
├── adapters/                     # 数据源适配器
│   ├── __init__.py
│   ├── base.py                   # 适配器基类
│   ├── telegram.py               # Telegram 适配器
│   ├── douban.py                 # 豆瓣适配器
│   ├── readwise.py               # Readwise 适配器
│   ├── strava.py                 # Strava 适配器
│   └── apple_health.py           # Apple Health 适配器
│
├── ai/                           # AI 相关
│   ├── __init__.py
│   ├── providers.py              # LLM 提供商
│   ├── summary_generator.py      # 总结生成
│   └── prompts.py                # Prompt 模板
│
├── github/                       # GitHub 集成
│   ├── __init__.py
│   ├── client.py                 # GitHub API 客户端
│   ├── issue_formatter.py        # Issue 格式化
│   └── templates/                # Markdown 模板
│
├── api/                          # REST API
│   ├── __init__.py
│   ├── main.py                   # FastAPI 应用
│   ├── routers/
│   │   ├── journals.py           # 日记相关 API
│   │   ├── entries.py            # 条目相关 API
│   │   ├── sync.py               # 同步相关 API
│   │   └── webhooks.py           # Webhook 接收
│
├── tasks/                        # 后台任务 (Celery)
│   ├── __init__.py
│   ├── celery_app.py             # Celery 配置
│   ├── sync_tasks.py             # 同步任务
│   └── merge_tasks.py            # 合并任务
│
├── web/                          # Web 管理界面 (可选)
│   ├── package.json
│   └── src/
│
├── tests/
├── scripts/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

### 8.2 适配器模式实现

```python
# adapters/base.py
"""
数据源适配器基类

所有数据源适配器必须继承此类并实现抽象方法
"""

from abc import ABC, abstractmethod
from typing import Iterator, Dict, Optional
from datetime import datetime

class DataSourceAdapter(ABC):
    """数据源适配器基类"""
    
    source_type: str = None  # 子类必须定义
    
    @abstractmethod
    async def authenticate(self, credentials: dict) -> bool:
        """验证凭据是否有效"""
        pass
    
    @abstractmethod
    async def sync(self, since: Optional[datetime] = None) -> Iterator[Dict]:
        """
        同步数据
        
        Args:
            since: 只同步此时间之后的数据
            
        Yields:
            标准化格式的数据条目
        """
        pass
    
    @abstractmethod
    def normalize(self, raw_data: dict) -> Dict:
        """
        将原始数据转换为标准格式
        
        标准格式：
        {
            'source_type': str,          # 数据源类型
            'source_id': str,            # 数据源唯一ID
            'content_type': str,         # 内容类型
            'title': str,                # 标题（可选）
            'content': str,              # Markdown 内容
            'url': str,                  # 原始链接（可选）
            'created_at': datetime,      # 创建时间
            'tags': List[str],           # 标签
            'metadata': dict,            # 原始元数据
        }
        """
        pass
    
    @abstractmethod
    async def test_connection(self) -> Dict:
        """测试连接，返回状态信息"""
        pass


# 适配器注册表
_ADAPTER_REGISTRY = {}

def register_adapter(source_type: str, adapter_class: type):
    """注册适配器"""
    _ADAPTER_REGISTRY[source_type] = adapter_class

def get_adapter(source_type: str, **kwargs) -> DataSourceAdapter:
    """获取适配器实例"""
    adapter_class = _ADAPTER_REGISTRY.get(source_type)
    if not adapter_class:
        raise ValueError(f"Unknown source type: {source_type}")
    return adapter_class(**kwargs)

# 使用示例
# register_adapter('readwise', ReadwiseAdapter)
# adapter = get_adapter('readwise', token='xxx')
```

---

## 9. 实施路线图

### Phase 1: 基础重构（2-3 周）

```
Week 1-2: 数据库引入
├── [ ] 设计并实现数据库模型
├── [ ] 迁移现有数据（GitHub Issue -> DB）
├── [ ] 重构 handlers.py 使用数据库存储
└── [ ] 实现跨天合并逻辑

Week 2-3: 核心功能完善
├── [ ] 实现 DailyMergeScheduler
├── [ ] 完善标签提取和存储
├── [ ] 实现 MediaFile 模型和图片管理
└── [ ] 添加单元测试和集成测试
```

### Phase 2: 数据源扩展（3-4 周）

```
Week 4-5: Readwise 集成
├── [ ] 实现 ReadwiseAdapter
├── [ ] OAuth/Token 认证流程
├── [ ] 定时同步任务
└── [ ] 内容格式化

Week 5-6: Strava 集成
├── [ ] 实现 StravaAdapter
├── [ ] OAuth2 授权流程
├── [ ] Webhook 接收端点
└── [ ] 活动数据展示

Week 6-7: 豆瓣集成（备选）
├── [ ] 调研 RSS 方案可行性
├── [ ] 实现 DoubanRSSAdapter
└── [ ] 或提供浏览器书签工具

Week 7-8: Apple Health
├── [ ] 设计 Health Auto Export 集成方案
├── [ ] 实现 webhook 接收
└── [ ] 健康数据格式化
```

### Phase 3: AI 和高级功能（2-3 周）

```
Week 9-10: AI 总结
├── [ ] 实现 SummaryGenerator
├── [ ] 支持多 LLM 提供商
├── [ ] 每日总结自动生成
└── [ ] 周报自动生成

Week 10-11: 高级功能
├── [ ] 搜索功能（全文检索）
├── [ ] 统计和可视化
├── [ ] 导出功能（PDF, Markdown）
└── [ ] 数据备份和恢复
```

### Phase 4: 优化和稳定（持续）

```
Week 12+: 优化
├── [ ] 性能优化（查询优化、缓存）
├── [ ] 监控和告警完善
├── [ ] 文档完善
├── [ ] 社区反馈处理
└── [ ] 新数据源探索
```

---

## 10. 关键决策建议

### 10.1 技术选型决策

| 决策项 | 推荐方案 | 理由 |
|--------|----------|------|
| **数据库** | SQLite (单机) / PostgreSQL (多用户) | 简单场景 SQLite 足够，扩展性好 |
| **ORM** | SQLAlchemy 2.0 | 成熟、文档完善、类型支持好 |
| **任务队列** | Celery + Redis | 稳定、生态丰富 |
| **LLM 默认** | OpenAI GPT-4 | 质量高，后续可支持多厂商 |
| **豆瓣方案** | RSS 优先 | 稳定可靠，降低维护成本 |
| **部署** | Docker Compose | 简单、可维护 |

### 10.2 风险控制

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 豆瓣方案不稳定 | 功能不可用 | 提供浏览器书签替代方案 |
| LLM API 成本 | 运营成本上升 | 支持本地模型 (Ollama) |
| 数据丢失 | 用户数据不可恢复 | 定期备份 + GitHub Issue 冗余 |
| GitHub API 限流 | 同步失败 | 实现指数退避重试 |

---

## 附录：关键代码片段

### A. 跨天判断工具

```python
from datetime import datetime, date
from zoneinfo import ZoneInfo

def is_same_day(dt1: datetime, dt2: datetime, timezone: str = "Asia/Shanghai") -> bool:
    """判断两个时间是否在同一个自然日（按指定时区）"""
    tz = ZoneInfo(timezone)
    return dt1.astimezone(tz).date() == dt2.astimezone(tz).date()

def get_user_today(timezone: str = "Asia/Shanghai") -> date:
    """获取用户当前时区的今天日期"""
    return datetime.now(ZoneInfo(timezone)).date()

def should_merge_journal(journal_date: date, user_timezone: str) -> bool:
    """判断日记是否应该被合并（日期早于今天）"""
    today = get_user_today(user_timezone)
    return journal_date < today
```

### B. 事务安全的合并操作

```python
from contextlib import contextmanager
from sqlalchemy.orm import Session

@contextmanager
def journal_merge_lock(db: Session, journal_id: int):
    """
    日记合并锁
    
    防止并发情况下重复合并同一篇日记
    """
    try:
        # 使用 SELECT FOR UPDATE 获取行锁
        journal = db.query(Journal).filter(
            Journal.id == journal_id
        ).with_for_update().first()
        
        if not journal:
            raise ValueError(f"Journal {journal_id} not found")
        
        if journal.status != JournalStatus.COLLECTING:
            raise ValueError(f"Journal {journal_id} is not in COLLECTING state")
        
        # 更新状态为合并中
        journal.status = JournalStatus.PENDING_MERGE
        db.commit()
        
        yield journal
        
        # 成功完成
        journal.status = JournalStatus.MERGED
        db.commit()
        
    except Exception:
        # 失败回滚
        db.rollback()
        # 恢复状态
        journal = db.query(Journal).get(journal_id)
        if journal:
            journal.status = JournalStatus.COLLECTING
            db.commit()
        raise
```

---

**报告完成日期**: 2024-02-12  
**版本**: v1.0  
**作者**: Munin Technical Review Agent
