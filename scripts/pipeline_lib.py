#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = CURRENT_DIR.parent
WORKSPACE = Path(os.getenv('XHS_PIPELINE_WORKSPACE') or os.getcwd()).resolve()
DEFAULT_RUNS_DIR = Path(os.getenv('XHS_PIPELINE_RUNS_DIR') or (WORKSPACE / 'xhs-copywriting-runs'))
TITLE_LIMIT = 20
BODY_LIMIT = 1000


def now_iso() -> str:
    return datetime.now().isoformat()


def slugify(text: str) -> str:
    text = (text or '').strip().lower()
    text = re.sub(r'[^\w\u4e00-\u9fff-]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    return text[:48] or 'run'


def safe_int(v: Any) -> int:
    if v is None:
        return 0
    if isinstance(v, int):
        return v
    s = str(v).replace(',', '').strip()
    m = re.match(r'^(\d+)', s)
    return int(m.group(1)) if m else 0


def ensure_run_dir(keyword: str = '', run_dir: str | None = None) -> Path:
    if run_dir:
        path = Path(run_dir).expanduser().resolve()
    else:
        ts = datetime.now().strftime('%Y%m%d-%H%M%S')
        path = DEFAULT_RUNS_DIR / f'{ts}-{slugify(keyword)}'
    for p in [path / 'inputs', path / 'ref', path / 'plan', path / 'drafts']:
        p.mkdir(parents=True, exist_ok=True)
    return path


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def read_text(path: Path, default: str = '') -> str:
    if not path.exists():
        return default
    return path.read_text()


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2))


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return default or {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return default or {}


def workflow_path(run_dir: Path) -> Path:
    return run_dir / 'workflow.json'


def load_workflow(run_dir: Path) -> dict[str, Any]:
    wf = read_json(workflow_path(run_dir), {})
    wf.setdefault('run_dir', str(run_dir))
    wf.setdefault('stage', 'initialized')
    wf.setdefault('history', [])
    return wf


def append_history(wf: dict[str, Any], event: str, payload: dict[str, Any] | None = None) -> None:
    wf.setdefault('history', []).append({
        'ts': now_iso(),
        'event': event,
        'payload': payload or {},
    })


def save_workflow(run_dir: Path, wf: dict[str, Any]) -> None:
    wf['updated_at'] = now_iso()
    wf['run_dir'] = str(run_dir)
    write_json(workflow_path(run_dir), wf)


def next_action_for_stage(stage: str) -> str:
    mapping = {
        'initialized': 'fetch_refs',
        'refs_fetched': 'generate_topic_options',
        'topic_options_generated': 'wait_user_choice',
        'topic_confirmed': 'generate_final_draft',
        'draft_generated': 'done',
    }
    return mapping.get(stage, 'inspect_state')


def summarize_status(run_dir: Path) -> dict[str, Any]:
    wf = load_workflow(run_dir)
    return {
        'ok': True,
        'run_dir': str(run_dir),
        'stage': wf.get('stage', 'initialized'),
        'next_action': next_action_for_stage(wf.get('stage', 'initialized')),
        'keyword': read_text(run_dir / 'inputs' / 'keyword.txt').strip(),
        'has_user_ip': (run_dir / 'inputs' / 'user_ip.md').exists(),
        'has_refs': (run_dir / 'ref' / 'articles.md').exists(),
        'has_seo_brief': (run_dir / 'ref' / 'seo-brief.md').exists(),
        'has_topic_options': (run_dir / 'plan' / 'topic-options.md').exists(),
        'has_chosen_topic': (run_dir / 'plan' / 'chosen-topic.json').exists(),
        'has_final_draft': (run_dir / 'drafts' / 'final.md').exists(),
        'workflow': wf,
    }


def find_xhs_bin() -> str | None:
    env_bin = os.getenv('XHS_PIPELINE_XHS_BIN')
    candidates = []
    if env_bin:
        candidates.append(Path(env_bin).expanduser())
    which_bin = shutil.which('xhs')
    if which_bin:
        candidates.append(Path(which_bin))
    candidates.extend([
        WORKSPACE / 'xiaohongshu-cli' / '.venv' / 'bin' / 'xhs',
        WORKSPACE / 'xiaohongshu-cli' / 'venv' / 'bin' / 'xhs',
        Path.home() / '.local' / 'bin' / 'xhs',
    ])
    for c in candidates:
        if c and Path(c).exists():
            return str(Path(c).resolve())
    return None


def install_hint() -> str:
    return (
        '未找到 xhs CLI。请先安装 xiaohongshu-cli，并确保 `xhs` 可执行。\n'
        '推荐方式：\n'
        '  1) uv tool install xiaohongshu-cli\n'
        '  2) 或 pipx install xiaohongshu-cli\n'
        '  3) 安装后执行 xhs login / xhs status 完成认证\n'
        '  4) 如 xhs 不在 PATH，可设置环境变量 XHS_PIPELINE_XHS_BIN'
    )


def preflight_xhs() -> dict[str, Any]:
    xhs_bin = find_xhs_bin()
    result = {
        'ok': False,
        'xhs_bin': xhs_bin,
        'installed': bool(xhs_bin),
        'authenticated': False,
        'message': '',
    }
    if not xhs_bin:
        result['message'] = install_hint()
        return result
    try:
        proc = subprocess.run([xhs_bin, 'status', '--json'], capture_output=True, text=True, timeout=30)
    except Exception as e:
        result['message'] = f'xhs status 执行失败：{e}'
        return result

    if proc.returncode != 0:
        result['message'] = (
            'xhs 已安装，但状态检查失败。请先执行 `xhs login` 完成登录，'
            '然后再运行本 skill。\n原始错误：\n' + (proc.stderr or proc.stdout)
        )
        return result

    try:
        data = json.loads(proc.stdout)
        result['authenticated'] = bool(data.get('data', {}).get('authenticated'))
    except Exception:
        result['message'] = 'xhs status 返回无法解析，请确认 xiaohongshu-cli 版本可用。'
        return result

    if not result['authenticated']:
        result['message'] = 'xhs 已安装，但当前未登录。请先执行 `xhs login` 或配置 cookies。'
        return result

    result['ok'] = True
    result['message'] = 'xhs 已安装且认证通过。'
    return result


def char_len(text: str) -> int:
    return len((text or '').strip())


def validate_title_length(title: str, limit: int = TITLE_LIMIT) -> None:
    if char_len(title) > limit:
        raise ValueError(f'标题超长：当前 {char_len(title)} 字，限制 {limit} 字。请压缩标题。')


def parse_final_markdown(content: str) -> dict[str, str]:
    title = ''
    body = ''
    tags = ''
    m = re.search(r'【标题】\s*\n(?P<title>[\s\S]*?)\n\s*【正文】\s*\n(?P<body>[\s\S]*?)\n\s*【标签】\s*\n(?P<tags>[\s\S]*)$', content.strip())
    if m:
        title = m.group('title').strip()
        body = m.group('body').strip()
        tags = m.group('tags').strip()
    return {'title': title, 'body': body, 'tags': tags}


def validate_final_markdown(content: str, title_limit: int = TITLE_LIMIT, body_limit: int = BODY_LIMIT) -> None:
    parsed = parse_final_markdown(content)
    if not parsed['title'] or not parsed['body']:
        raise ValueError('final.md 格式不正确，必须包含【标题】【正文】【标签】三段。')
    validate_title_length(parsed['title'], title_limit)
    if char_len(parsed['body']) > body_limit:
        raise ValueError(f'正文超长：当前 {char_len(parsed["body"])} 字，限制 {body_limit} 字。请压缩正文。')
