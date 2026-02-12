# Munin 测试方案

本文档描述 Munin 项目的测试策略和实现方案。

## 测试目标

1. **单元测试**：验证各个模块的独立功能正确性
2. **集成测试**：验证端到端流程的正确性
3. **Media Group 专项测试**：确保多图相册功能稳定可靠

## 测试框架

- **pytest**: 主要测试框架
- **pytest-asyncio**: 支持异步测试
- **pytest-mock**: Mock 工具
- **respx**: 模拟 HTTP 请求（GitHub API）
- **factory-boy**: 测试数据工厂

## 目录结构

```
tests/
├── __init__.py
├── conftest.py              # 共享 fixtures
├── README.md                # 本文档
├── unit/                    # 单元测试
│   ├── __init__.py
│   ├── test_config.py       # 配置管理测试
│   ├── test_github_client.py # GitHub API 测试
│   └── test_handlers.py     # 消息处理器测试（重点）
├── integration/             # 集成测试
│   ├── __init__.py
│   ├── test_bot_flow.py     # 端到端流程测试
│   └── test_media_group.py  # Media Group 专项测试
└── fixtures/                # 测试数据
    ├── sample_messages.json # 消息样本
    └── sample_photos/       # 测试图片
        ├── test_image_1.jpg
        ├── test_image_2.jpg
        └── test_image_3.png
```

## 运行测试

```bash
# 安装测试依赖
pip install -r requirements-dev.txt

# 运行所有测试
pytest

# 运行特定测试
pytest tests/unit/test_handlers.py
pytest tests/integration/test_media_group.py

# 带覆盖率报告
pytest --cov=bot --cov-report=html

# 只运行单元测试
pytest tests/unit/

# 只运行集成测试
pytest tests/integration/ -v

# 运行特定场景
pytest -k "media_group" -v
pytest -k "single_photo" -v
```

## 环境变量

测试使用以下环境变量（可在 `.env.test` 中配置）：

```bash
# GitHub (测试用，可使用 fake token)
GITHUB_TOKEN=test_token
GITHUB_OWNER=test_owner
GITHUB_REPO=test_repo

# Telegram (测试用)
TELEGRAM_BOT_TOKEN=test_token
ALLOWED_USER_IDS=123456789,987654321

# 时区
JOURNAL_TZ=Asia/Shanghai
```

## Mock 策略

### Telegram API

使用 `unittest.mock.AsyncMock` 模拟：
- `Update` 对象
- `Message` 对象
- `ContextTypes.DEFAULT_TYPE`
- `Bot.get_file()` 和 `file.download_to_memory()`

### GitHub API

使用 `respx` 模拟 HTTP 请求：
- `POST /repos/{owner}/{repo}/issues` - 创建 Issue
- `PUT /repos/{owner}/{repo}/contents/{path}` - 上传文件
- `GET /repos/{owner}/{repo}/contents/{path}` - 检查文件存在
- `POST /repos/{owner}/{repo}/issues/{number}/labels` - 添加标签

## 关键测试场景

### 单元测试

#### test_handlers.py

1. **单张图片处理**
   - 正常流程
   - 权限检查
   - 空消息处理

2. **Media Group 处理**（新功能）
   - 识别同组消息
   - 收集多张图片
   - 等待机制
   - 超时处理

3. **文本处理**
   - 标签提取（#标签）
   - 标题提取
   - Caption 处理

#### test_github_client.py

1. **Issue 创建**
   - 正常创建
   - 带标签创建
   - 自动添加 journal_label

2. **文件上传**
   - 新文件上传
   - 覆盖已有文件
   - 错误处理

3. **API 错误处理**
   - 认证失败
   - 限流处理
   - 网络超时

#### test_config.py

1. **配置加载**
   - 从环境变量加载
   - 从 .env 文件加载
   - 默认值处理

2. **配置校验**
   - 必填项检查
   - 时区解析
   - 用户 ID 列表解析

### 集成测试

#### test_media_group.py

1. **完整 Media Group 流程**
   - 3 张图 + caption
   - 5 张图 + caption
   - 10 张图（上限测试）

2. **超时场景**
   - 只收到部分图片
   - 超时后处理

3. **并发场景**
   - 多个用户同时发送
   - 同一用户快速发送多组

#### test_bot_flow.py

1. **单张图片 + 文字**
2. **多张图片（Media Group）+ 文字**
3. **纯文字消息**
4. **只有图片无文字**
5. **网络错误重试**
6. **GitHub API 限流**

## 测试数据

### 样本消息 (fixtures/sample_messages.json)

包含以下场景的测试数据：
- 单张图片消息
- Media Group 消息（3张、5张、10张）
- 纯文本消息
- 带标签的消息
- 无权限用户消息

### 样本图片 (fixtures/sample_photos/)

- `test_image_1.jpg` - 小尺寸 JPEG
- `test_image_2.jpg` - 中等尺寸 JPEG
- `test_image_3.png` - PNG 格式

## 覆盖率目标

- **单元测试**: > 80%
- **集成测试**: 覆盖主要用户场景
- **关键路径** (handlers.py): > 90%

## 持续集成

建议在 CI 中运行：

```yaml
# .github/workflows/test.yml
- name: Run tests
  run: |
    pip install -r requirements-dev.txt
    pytest --cov=bot --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v3
```

## 注意事项

1. **异步测试**: 所有涉及 Telegram API 的测试都是异步的，使用 `@pytest.mark.asyncio`
2. **HTTP Mock**: 使用 `respx` 而不是 `responses`，因为 `respx` 支持 `httpx`
3. **临时文件**: 测试图片使用内存中的 bytes，不依赖实际文件系统
4. **隔离性**: 每个测试独立运行，不共享状态
