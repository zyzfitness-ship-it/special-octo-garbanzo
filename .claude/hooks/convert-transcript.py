#!/usr/bin/env python3
"""
Convert Claude transcript jsonl to clean Markdown
Usage: python3 convert-transcript.py <input.jsonl> <output.md>
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def extract_text(content):
    """content에서 text만 추출 (thinking, tool_use, signature 제외)"""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text':
                text = item.get('text', '').strip()
                if text:
                    texts.append(text)
        return '\n\n'.join(texts)
    return ''


def convert_to_markdown(jsonl_path, output_path=None):
    """jsonl 파일을 마크다운으로 변환"""
    messages = []

    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            msg_type = data.get('type')

            # User 메시지 처리
            if msg_type == 'user':
                content = data.get('message', {}).get('content') or data.get('content')
                text = extract_text(content)
                # 무시할 메시지 필터링
                if text and not any(skip in text for skip in [
                    '[Request interrupted',
                    'Caveat:',
                    '<command-name>',
                    '<local-command',
                    '<system-reminder>'
                ]):
                    messages.append(('user', text))

            # Assistant 메시지 처리
            elif msg_type == 'assistant':
                content = data.get('message', {}).get('content') or data.get('content')
                text = extract_text(content)
                if text:
                    messages.append(('assistant', text))

    # 연속된 같은 역할 메시지 병합
    merged = []
    for role, text in messages:
        if merged and merged[-1][0] == role:
            merged[-1] = (role, merged[-1][1] + '\n\n' + text)
        else:
            merged.append((role, text))

    # Markdown 생성
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    md_lines = [f"# Session Backup - {timestamp}\n"]

    for role, text in merged:
        if role == 'user':
            md_lines.append(f"## 👤 User\n\n{text}\n")
        else:
            md_lines.append(f"## 🤖 Assistant\n\n{text}\n")

    md_content = '\n'.join(md_lines)

    # 파일 저장
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        return output_path

    return md_content


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 convert-transcript.py <input.jsonl> [output.md]")
        sys.exit(1)

    input_path = sys.argv[1]

    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        # 기본 출력 경로: 같은 이름의 .md 파일
        output_path = Path(input_path).with_suffix('.md')

    result = convert_to_markdown(input_path, output_path)
    print(f"Converted: {output_path}")


if __name__ == '__main__':
    main()
