# ZoomMind 部署说明

## 推荐方案：Render 单服务部署

这个项目现在支持一个服务同时托管前端和后端，远程被试只需要打开同一个 URL。

1. 把仓库推到 GitHub。
2. 在 Render 新建 Blueprint，选择这个仓库。
3. Render 会读取 `render.yaml`，用 Docker 构建并启动免费 Web Service。
4. 默认使用你当前的 MiniMax 配置。Render 会要求你手动填写 `ZOOMMIND_LLM_API_KEY`，不要把 key 写进仓库。

## MiniMax 配置

`render.yaml` 已按当前本地配置写好：

```text
ZOOMMIND_LLM_PROVIDER=openai-compatible
ZOOMMIND_LLM_BASE_URL=https://api.minimaxi.com/v1
ZOOMMIND_LLM_MODEL=MiniMax-M2
ZOOMMIND_LLM_TEMPERATURE=1.0
ZOOMMIND_LLM_REASONING_SPLIT=true
```

你只需要在 Render 的 Environment 里填 `ZOOMMIND_LLM_API_KEY`。Blueprint 里的 `sync: false` 会让 Render 在创建服务时提示你输入这个密钥。

## 数据保存

当前 `render.yaml` 使用免费方案：

```text
DATABASE_URL=sqlite:///./app.db
```

远程实验日志、状态快照、对话和图谱会写入服务内的 SQLite 文件。免费 Render 不提供 persistent disk，服务重启、休眠唤醒或重新部署后数据可能丢失。

每轮远程测试结束后，打开一次最终导出链接。这个链接会先创建 `end` 快照，再下载该 session 的完整 JSON：

```text
https://knowledge-cartography.onrender.com/api/export/session/{session_id}/final
```

例如学习页地址是：

```text
https://knowledge-cartography.onrender.com/learn/abc-123
```

最终导出地址就是：

```text
https://knowledge-cartography.onrender.com/api/export/session/abc-123/final
```

调试时也可以导出全量数据或单独行为日志：

```text
https://knowledge-cartography.onrender.com/api/export
https://knowledge-cartography.onrender.com/api/export/events.csv
```

`/api/export` 返回完整 JSON，适合备份。`/api/export/events.csv` 返回行为日志 CSV，适合快速分析。

## 本地生产模式验证

```bash
docker build -t zoommind .
docker run --rm -p 8000:8000 -e DATABASE_URL=sqlite:////tmp/zoommind.db zoommind
```

然后打开：

```text
http://localhost:8000
```

## 远程测试注意事项

不要把正式实验和随意调试混在同一个部署服务里。正式收数前，建议新建一次服务或清空数据库，保证日志不混入测试数据。
