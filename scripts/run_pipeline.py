#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR))

from pipeline_lib import (  # noqa: E402
    BODY_LIMIT,
    TITLE_LIMIT,
    append_history,
    ensure_run_dir,
    load_workflow,
    parse_final_markdown,
    preflight_xhs,
    save_workflow,
    summarize_status,
    validate_final_markdown,
    validate_title_length,
    write_json,
    write_text,
)

FETCH_SCRIPT = CURRENT_DIR / 'fetch_refs.py'


def cmd_doctor(_args):
    result = preflight_xhs()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result['ok']:
        sys.exit(1)


def cmd_init(args):
    run_dir = ensure_run_dir(args.keyword, args.run_dir or None)
    if args.keyword:
        write_text(run_dir / 'inputs' / 'keyword.txt', args.keyword)
    if args.user_ip_file:
        write_text(run_dir / 'inputs' / 'user_ip.md', Path(args.user_ip_file).read_text())
    elif args.user_ip_text:
        write_text(run_dir / 'inputs' / 'user_ip.md', args.user_ip_text)

    wf = load_workflow(run_dir)
    wf['stage'] = 'initialized'
    wf['keyword'] = args.keyword
    append_history(wf, 'initialized', {'keyword': args.keyword})
    save_workflow(run_dir, wf)
    print(json.dumps(summarize_status(run_dir), ensure_ascii=False, indent=2))


def cmd_fetch(args):
    cmd = [sys.executable, str(FETCH_SCRIPT), '--keyword', args.keyword, '--count', str(args.count), '--pages', str(args.pages), '--run-dir', args.run_dir]
    if args.user_ip_file:
        cmd += ['--user-ip-file', args.user_ip_file]
    elif args.user_ip_text:
        cmd += ['--user-ip-text', args.user_ip_text]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout or proc.stderr)
        sys.exit(proc.returncode)
    print(proc.stdout)


def cmd_status(args):
    run_dir = Path(args.run_dir)
    print(json.dumps(summarize_status(run_dir), ensure_ascii=False, indent=2))


def cmd_save_plan(args):
    run_dir = Path(args.run_dir)
    if args.plan_file:
        content = Path(args.plan_file).read_text()
    else:
        content = args.plan_text
    if not content.strip():
        raise SystemExit('plan content is empty')
    write_text(run_dir / 'plan' / 'topic-options.md', content)
    wf = load_workflow(run_dir)
    wf['stage'] = 'topic_options_generated'
    wf['topic_options_path'] = str(run_dir / 'plan' / 'topic-options.md')
    append_history(wf, 'topic_options_generated', {})
    save_workflow(run_dir, wf)
    print(json.dumps(summarize_status(run_dir), ensure_ascii=False, indent=2))


def cmd_choose_topic(args):
    run_dir = Path(args.run_dir)
    if args.title:
        validate_title_length(args.title, TITLE_LIMIT)
    chosen = {
        'option_index': args.option,
        'chosen_title': args.title,
        'chosen_topic_outline': args.topic_outline,
        'chosen_summary': args.summary,
        'user_note': args.user_note,
        'title_limit': TITLE_LIMIT,
        'body_limit': BODY_LIMIT,
    }
    write_json(run_dir / 'plan' / 'chosen-topic.json', chosen)
    md = []
    md.append('# 已确认选题')
    md.append('')
    md.append(f'- 方案编号: {args.option}')
    if args.title:
        md.append(f'- 采用标题: {args.title}')
        md.append(f'- 标题长度: {len(args.title)} / {TITLE_LIMIT}')
    if args.summary:
        md.append(f'- 选题总结: {args.summary}')
    if args.topic_outline:
        md.append('')
        md.append('## 选题大纲')
        md.append(args.topic_outline)
    if args.user_note:
        md.append('')
        md.append('## 用户补充')
        md.append(args.user_note)
    write_text(run_dir / 'plan' / 'chosen-topic.md', '\n'.join(md) + '\n')

    wf = load_workflow(run_dir)
    wf['stage'] = 'topic_confirmed'
    wf['chosen_topic_path'] = str(run_dir / 'plan' / 'chosen-topic.json')
    wf['chosen_option_index'] = args.option
    wf['chosen_title'] = args.title
    append_history(wf, 'topic_confirmed', {'option': args.option, 'title': args.title})
    save_workflow(run_dir, wf)
    print(json.dumps(summarize_status(run_dir), ensure_ascii=False, indent=2))


def cmd_save_draft(args):
    run_dir = Path(args.run_dir)
    if args.draft_file:
        content = Path(args.draft_file).read_text()
    else:
        content = args.draft_text
    if not content.strip():
        raise SystemExit('draft content is empty')
    validate_final_markdown(content, title_limit=TITLE_LIMIT, body_limit=BODY_LIMIT)
    write_text(run_dir / 'drafts' / 'final.md', content)
    parsed = parse_final_markdown(content)
    wf = load_workflow(run_dir)
    wf['stage'] = 'draft_generated'
    wf['final_draft_path'] = str(run_dir / 'drafts' / 'final.md')
    wf['final_title_length'] = len(parsed['title'])
    wf['final_body_length'] = len(parsed['body'])
    append_history(wf, 'draft_generated', {'title_len': len(parsed['title']), 'body_len': len(parsed['body'])})
    save_workflow(run_dir, wf)
    print(json.dumps(summarize_status(run_dir), ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Manage XHS copywriting pipeline runs.')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('doctor')
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser('init')
    p.add_argument('--keyword', required=True)
    p.add_argument('--run-dir', default='')
    p.add_argument('--user-ip-text', default='')
    p.add_argument('--user-ip-file', default='')
    p.set_defaults(func=cmd_init)

    p = sub.add_parser('fetch')
    p.add_argument('--keyword', required=True)
    p.add_argument('--run-dir', required=True)
    p.add_argument('--count', type=int, default=10)
    p.add_argument('--pages', type=int, default=2)
    p.add_argument('--user-ip-text', default='')
    p.add_argument('--user-ip-file', default='')
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser('status')
    p.add_argument('--run-dir', required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser('save-plan')
    p.add_argument('--run-dir', required=True)
    p.add_argument('--plan-file', default='')
    p.add_argument('--plan-text', default='')
    p.set_defaults(func=cmd_save_plan)

    p = sub.add_parser('choose-topic')
    p.add_argument('--run-dir', required=True)
    p.add_argument('--option', type=int, required=True)
    p.add_argument('--title', default='')
    p.add_argument('--summary', default='')
    p.add_argument('--topic-outline', default='')
    p.add_argument('--user-note', default='')
    p.set_defaults(func=cmd_choose_topic)

    p = sub.add_parser('save-draft')
    p.add_argument('--run-dir', required=True)
    p.add_argument('--draft-file', default='')
    p.add_argument('--draft-text', default='')
    p.set_defaults(func=cmd_save_draft)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
