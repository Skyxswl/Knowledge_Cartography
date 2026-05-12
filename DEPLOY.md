# ZoomMind 部署说明

## 推荐方案：Render 单服务部署

这个项目现在支持一个服务同时托管前端和后端，远程被试只需要打开同一个 URL。

1. 把仓库推到 GitHub。
2. 在 Render 新建 Blueprint，选择这个仓库。
3. Render 会读取 `render.yaml`，用 Docker 构建并启动服务。
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

`render.yaml` 已配置持久化磁盘：

```text
DATABASE_URL=sqlite:////data/app.db
```

远程实验日志、状态快照、对话和图谱都会写入这个 SQLite 文件。注意：如果删除 Render 服务或磁盘，数据也会丢失。

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
