#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR))

from pipeline_lib import (  # noqa: E402
    append_history,
    ensure_run_dir,
    find_xhs_bin,
    install_hint,
    load_workflow,
    now_iso,
    preflight_xhs,
    safe_int,
    save_workflow,
    write_json,
    write_text,
)

STOP_CHUNKS = {'真的', '超简单', '有用', '结果', '进来看', '看过来', '姐妹', '测测吧', '就能出', '就能测'}


def run_xhs(args: list[str]) -> dict[str, Any]:
    xhs_bin = find_xhs_bin()
    if not xhs_bin:
        raise FileNotFoundError(install_hint())
    cmd = [xhs_bin, *args, '--json']
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f'Command failed: {" ".join(cmd)}\nSTDERR:\n{proc.stderr}')
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f'Invalid JSON from xhs:\n{proc.stdout[:1200]}') from e


def search_candidates(keyword: str, pages: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        data = run_xhs(['search', keyword, '--sort', 'popular', '--page', str(page)])
        if not data.get('ok'):
            continue
        for item in data.get('data', {}).get('items', []):
            if item.get('model_type') != 'note':
                continue
            note = item.get('note_card', {})
            interact = note.get('interact_info', {})
            candidate = {
                'id': item.get('id'),
                'xsec_token': item.get('xsec_token', ''),
                'title': note.get('display_title') or note.get('title') or '',
                'author': (note.get('user') or {}).get('nickname') or (note.get('user') or {}).get('nick_name') or '',
                'author_id': (note.get('user') or {}).get('user_id') or '',
                'liked_count': safe_int(interact.get('liked_count')),
                'comment_count': safe_int(interact.get('comment_count')),
                'collected_count': safe_int(interact.get('collected_count')),
                'shared_count': safe_int(interact.get('shared_count')),
            }
            if candidate['id'] and candidate['xsec_token']:
                candidate['score'] = (
                    candidate['liked_count']
                    + candidate['comment_count'] * 12
                    + candidate['collected_count'] * 4
                    + candidate['shared_count'] * 6
                )
                items.append(candidate)
    dedup = {}
    for item in items:
        dedup[item['id']] = item
    return sorted(dedup.values(), key=lambda x: x['score'], reverse=True)


def read_note(note_id: str, xsec_token: str) -> dict[str, Any]:
    return run_xhs(['read', note_id, '--xsec-token', xsec_token])


def summarize_note(detail: dict[str, Any], rank: int, keyword: str) -> dict[str, Any]:
    item = (detail.get('data', {}).get('items') or [{}])[0]
    note = item.get('note_card', {})
    user = note.get('user', {})
    interact = note.get('interact_info', {})
    tags = [t.get('name') for t in note.get('tag_list', []) if t.get('name')]
    return {
        'rank': rank,
        'keyword': keyword,
        'note_id': note.get('note_id') or item.get('id'),
        'title': note.get('title') or note.get('display_title') or '',
        'author': user.get('nickname') or user.get('nick_name') or '',
        'author_id': user.get('user_id') or '',
        'desc': note.get('desc') or '',
        'liked_count': safe_int(interact.get('liked_count')),
        'comment_count': safe_int(interact.get('comment_count')),
        'collected_count': safe_int(interact.get('collected_count')),
        'share_count': safe_int(interact.get('share_count') or interact.get('shared_count')),
        'tags': tags,
        'ip_location': note.get('ip_location') or '',
        'time': note.get('time') or '',
    }


def write_note_files(ref_dir: Path, summary: dict[str, Any], raw: dict[str, Any]):
    note_id = summary['note_id']
    rank = summary['rank']
    prefix = f'note-{rank:02d}-{note_id}'
    write_json(ref_dir / f'{prefix}.json', raw)
    md = []
    md.append(f"# 参考文章 {rank}: {summary['title']}")
    md.append('')
    md.append(f"- note_id: {summary['note_id']}")
    md.append(f"- 作者: {summary['author']}")
    md.append(f"- 点赞: {summary['liked_count']}")
    md.append(f"- 评论: {summary['comment_count']}")
    md.append(f"- 收藏: {summary['collected_count']}")
    md.append(f"- 分享: {summary['share_count']}")
    if summary['ip_location']:
        md.append(f"- IP属地: {summary['ip_location']}")
    if summary['tags']:
        md.append(f"- 标签: {' / '.join(summary['tags'])}")
    md.append('')
    md.append('## 正文')
    md.append(summary['desc'] or '（无正文）')
    md.append('')
    write_text(ref_dir / f'{prefix}.md', '\n'.join(md))


def derive_title_chunks(title: str) -> list[str]:
    raw = re.sub(r'[#@].*', '', title)
    raw = re.sub(r'[❗️❓✅🔥🤔👏✨💡🧪💰…～~]+', ' ', raw)
    parts = re.split(r'[\s,，。！？!？：:、/（）()【】\-|｜]+', raw)
    out = []
    for p in parts:
        p = p.strip()
        if 2 <= len(p) <= 12 and p not in STOP_CHUNKS and not p.isdigit():
            out.append(p)
    return out


def write_seo_brief(run_dir: Path, keyword: str, summaries: list[dict[str, Any]]):
    tag_counter = Counter()
    title_counter = Counter()
    for s in summaries:
        for t in s.get('tags', []):
            if t and t != keyword:
                tag_counter[t] += 1
        for chunk in derive_title_chunks(s.get('title', '')):
            if chunk != keyword:
                title_counter[chunk] += 1

    secondary = [k for k, _ in tag_counter.most_common(12)]
    title_phrases = [k for k, _ in title_counter.most_common(10)]
    all_terms = []
    seen = set([keyword])
    for term in secondary + title_phrases:
        if term not in seen:
            all_terms.append(term)
            seen.add(term)

    lines = [f'# SEO Brief：{keyword}', '']
    lines.append(f'- 主关键词：{keyword}')
    lines.append(f'- 次关键词建议：{" / ".join(all_terms[:12]) if all_terms else "（请结合参考标题自行提炼）"}')
    lines.append('')
    lines.append('## SEO 布局要求')
    lines.append('- 标题尽量前置主关键词或核心搜索意图。')
    lines.append('- 开头前 100 字内自然出现主关键词 + 1~2 个次关键词。')
    lines.append('- 正文中段围绕用户搜索意图自然埋词，不要堆词。')
    lines.append('- 标签优先覆盖主关键词、次关键词、场景词、避坑词。')
    lines.append('- 关键词必须自然融入，不允许为了 SEO 生硬重复。')
    lines.append('')
    lines.append('## 标题/搜索意图观察')
    for s in summaries[:10]:
        lines.append(f'- {s.get("title", "")}')
    lines.append('')
    lines.append('## 高频标签')
    if secondary:
        for k, v in tag_counter.most_common(12):
            lines.append(f'- {k}（{v}）')
    else:
        lines.append('- （无标签统计）')
    write_text(run_dir / 'ref' / 'seo-brief.md', '\n'.join(lines) + '\n')


def write_manifest(run_dir: Path, keyword: str, summaries: list[dict[str, Any]]):
    ref_dir = run_dir / 'ref'
    manifest = {
        'keyword': keyword,
        'count': len(summaries),
        'generated_at': now_iso(),
        'articles': summaries,
    }
    write_json(ref_dir / 'articles.json', manifest)

    lines = [f'# 小红书参考爆文汇总：{keyword}', '']
    lines.append(f'- 文章数量: {len(summaries)}')
    lines.append(f'- 生成时间: {manifest["generated_at"]}')
    lines.append('')
    for s in summaries:
        lines.append(f'## [{s["rank"]}] {s["title"]}')
        lines.append(f'- 作者: {s["author"]}')
        lines.append(f'- 互动数据: 点赞 {s["liked_count"]} / 评论 {s["comment_count"]} / 收藏 {s["collected_count"]} / 分享 {s["share_count"]}')
        if s['tags']:
            lines.append(f'- 标签: {" / ".join(s["tags"])}')
        if s['ip_location']:
            lines.append(f'- IP属地: {s["ip_location"]}')
        excerpt = (s['desc'] or '').strip().replace('\r', '')
        if len(excerpt) > 500:
            excerpt = excerpt[:500] + '…'
        lines.append('- 正文摘要:')
        lines.append(excerpt or '（无正文）')
        lines.append('')
    write_text(ref_dir / 'articles.md', '\n'.join(lines))
    write_seo_brief(run_dir, keyword, summaries)


def main():
    parser = argparse.ArgumentParser(description='Fetch top XHS reference posts into a pipeline run directory.')
    parser.add_argument('--keyword', required=True)
    parser.add_argument('--count', type=int, default=10)
    parser.add_argument('--pages', type=int, default=2)
    parser.add_argument('--run-dir', default='')
    parser.add_argument('--sleep', type=float, default=0.8)
    parser.add_argument('--user-ip-text', default='')
    parser.add_argument('--user-ip-file', default='')
    args = parser.parse_args()

    preflight = preflight_xhs()
    if not preflight['ok']:
        print(json.dumps({'ok': False, 'error': preflight['message']}, ensure_ascii=False, indent=2))
        sys.exit(1)

    run_dir = ensure_run_dir(args.keyword, args.run_dir or None)
    write_text(run_dir / 'inputs' / 'keyword.txt', args.keyword)

    if args.user_ip_file:
        write_text(run_dir / 'inputs' / 'user_ip.md', Path(args.user_ip_file).read_text())
    elif args.user_ip_text:
        write_text(run_dir / 'inputs' / 'user_ip.md', args.user_ip_text)

    candidates = search_candidates(args.keyword, args.pages)
    selected = candidates[: args.count]
    summaries: list[dict[str, Any]] = []

    for idx, c in enumerate(selected, start=1):
        raw = read_note(c['id'], c['xsec_token'])
        summary = summarize_note(raw, idx, args.keyword)
        summary['search_score'] = c['score']
        summaries.append(summary)
        write_note_files(run_dir / 'ref', summary, raw)
        time.sleep(max(args.sleep, 0))

    write_manifest(run_dir, args.keyword, summaries)
    wf = load_workflow(run_dir)
    wf['stage'] = 'refs_fetched'
    wf['keyword'] = args.keyword
    wf['ref_count'] = len(summaries)
    wf['ref_articles_path'] = str(run_dir / 'ref' / 'articles.md')
    wf['seo_brief_path'] = str(run_dir / 'ref' / 'seo-brief.md')
    append_history(wf, 'refs_fetched', {
        'keyword': args.keyword,
        'fetched_count': len(summaries),
    })
    save_workflow(run_dir, wf)

    result = {
        'ok': True,
        'run_dir': str(run_dir),
        'keyword': args.keyword,
        'requested_count': args.count,
        'fetched_count': len(summaries),
        'files': {
            'articles_md': str(run_dir / 'ref' / 'articles.md'),
            'articles_json': str(run_dir / 'ref' / 'articles.json'),
            'seo_brief_md': str(run_dir / 'ref' / 'seo-brief.md'),
            'workflow_json': str(run_dir / 'workflow.json'),
            'user_ip_md': str(run_dir / 'inputs' / 'user_ip.md'),
        },
        'top_titles': [s['title'] for s in summaries],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)
