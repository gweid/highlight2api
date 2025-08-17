# Highlight2API

将 Highlight AI 转换为 OpenAI 兼容的 API 接口，支持流式响应、工具调用和图片处理。

## 🚀 一键部署

```bash
docker run -d -p 3003:3003 --name highlight2api ghcr.io/jhhgiyv/highlight2api:latest
```

## 📝 获取 API Key

部署完成后，打开 `http://你的服务器IP:3003/highlight_login` 根据页面提示获取 API Key。

## 🎯 特性

- ✅ 完全兼容 OpenAI API 格式
- ✅ 支持流式和非流式响应
- ✅ 支持图片上传和分析
- ✅ 支持工具调用 (Function Calling)
- ✅ 自动处理认证和令牌刷新
- ✅ 内置文件缓存机制
- ✅ 支持多模态对话