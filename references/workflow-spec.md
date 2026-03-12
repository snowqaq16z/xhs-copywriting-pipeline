# Workflow Spec (v1.1)

## Stage values
- `initialized`
- `refs_fetched`
- `topic_options_generated`
- `topic_confirmed`
- `draft_generated`

## Required files by stage

### refs_fetched
- `inputs/keyword.txt`
- `ref/articles.md`
- `ref/articles.json`
- `ref/seo-brief.md`
- `workflow.json`

### topic_options_generated
- all files above
- `plan/topic-options.md`

### topic_confirmed
- all files above
- `plan/chosen-topic.json`
- `plan/chosen-topic.md`

### draft_generated
- all files above
- `drafts/final.md`

## Dependency checks
在抓取前，先运行：

```bash
python3 scripts/run_pipeline.py doctor
```

如果失败，应先提示：
- 安装 `xiaohongshu-cli`
- 完成 `xhs login` / `xhs status`
- 或设置 `XHS_PIPELINE_XHS_BIN`

## Recommended operator flow
1. doctor
2. init / fetch refs
3. read refs + seo brief + user IP
4. write topic options
5. save plan
6. wait for user choice
7. choose topic
8. generate final draft
9. save draft

## Hard limits
- 选题核心切入点：20 字以内
- 爆款标题候选：20 字以内
- 最终标题：20 字以内
- 最终正文：1000 字以内
