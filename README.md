# Sakana AI Research RSS

自动抓取 Sakana AI 研究博客列表，筛选更像论文、基准、算法、智能体、模型、LLM、神经网络和进化计算相关的英文研究文章，生成可订阅 RSS。

## 订阅地址

```text
https://cathyliucx.github.io/rss/sakana-research.xml
```

适合接入：

```text
NetNewsWire -> netnewswire-mcp -> Codex / DeepSeek -> AI research brief
```

## 抓取源

```text
https://sakana.ai/blog/?label=research
```

## 保留规则

默认规则在 `config.yaml` 中维护：

- 优先保留英文研究标题。
- 标题、摘要或链接中包含 `paper`、`benchmark`、`algorithm`、`agent`、`model`、`LLM`、`neural`、`evolution` 等研究词。
- 排除产品发布、招聘、融资、合作、日文营销文案。

## 本地运行

```bash
uv sync
uv run python generate_feed.py
```

输出：

```text
docs/sakana-research.xml
```

## 测试

```bash
uv run pytest
```

## 自动更新

GitHub Actions 每 6 小时运行一次 `generate_feed.py`，如果 `docs/sakana-research.xml` 有变化，会自动提交更新。

如果最终发布地址必须固定为：

```text
https://cathyliucx.github.io/rss/sakana-research.xml
```

请确保 GitHub Pages 的发布仓库/目录会暴露 `rss/sakana-research.xml`。本项目默认生成文件名为 `sakana-research.xml`，必要时可由 Pages 仓库同步到 `/rss/` 目录。
