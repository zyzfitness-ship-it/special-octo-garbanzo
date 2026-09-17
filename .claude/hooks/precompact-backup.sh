#!/bin/bash
# PreCompact Hook: transcript를 깔끔한 Markdown으로 백업 + 알림 + 클립보드 복사

# 디버그 로그
DEBUG_LOG="/tmp/precompact-debug.log"
echo "=== $(date) ===" >> "$DEBUG_LOG"
echo "PWD: $(pwd)" >> "$DEBUG_LOG"

# stdin에서 JSON 읽기
INPUT=$(cat)
echo "INPUT: $INPUT" >> "$DEBUG_LOG"

# input JSON에서 직접 추출 (경로 계산 불필요)
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
PROJECT_DIR=$(echo "$INPUT" | jq -r '.cwd // empty')
PROJECT_NAME=$(basename "$PROJECT_DIR")
TRIGGER=$(echo "$INPUT" | jq -r '.trigger // "auto"')

echo "TRANSCRIPT: $TRANSCRIPT" >> "$DEBUG_LOG"

if [ -z "$TRANSCRIPT" ]; then
    echo "Transcript not found - exiting" >> "$DEBUG_LOG"
    exit 0
fi
echo "SESSION_ID: $SESSION_ID" >> "$DEBUG_LOG"

# 대화명 결정 (우선순위: customName > preview > 프로젝트명)
SESSION_TITLE=""
if [ -n "$SESSION_ID" ]; then
    # 1. customName 확인
    if [ -f ~/.claude/session-names.json ]; then
        SESSION_TITLE=$(jq -r --arg id "$SESSION_ID" '.[$id] // ""' ~/.claude/session-names.json 2>/dev/null)
    fi
    # 2. customName 없으면 preview 사용
    if [ -z "$SESSION_TITLE" ] && [ -f ~/.claude/session-previews.json ]; then
        SESSION_TITLE=$(jq -r --arg id "$SESSION_ID" '.[$id] // ""' ~/.claude/session-previews.json 2>/dev/null)
    fi
fi
# 3. 둘 다 없으면 프로젝트명
[ -z "$SESSION_TITLE" ] && SESSION_TITLE="$PROJECT_NAME"

# 백업 파일 경로 (session_id 앞 8자를 파일명에 박아 핸드오프 격리의 fallback 식별자로 사용)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SID8=$(echo "$SESSION_ID" | cut -c1-8)
BACKUP_DIR=~/.claude/backups
mkdir -p "$BACKUP_DIR"
if [ -n "$SID8" ]; then
    BACKUP_FILE="${BACKUP_DIR}/session-${TIMESTAMP}-${SID8}.md"
else
    BACKUP_FILE="${BACKUP_DIR}/session-${TIMESTAMP}.md"
fi

# Python 스크립트로 마크다운 변환
HOOK_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
python3 "$HOOK_DIR/convert-transcript.py" "$TRANSCRIPT" "$BACKUP_FILE"

# 세션 규모에 따라 압축 방식 자동 선택
# (블로그 "압축은 멈춤이 아니라 배치다"의 scheduler 원리 미니멀 구현:
#  context 사용량/블록 나이를 보고 단일 vs 병렬 압축을 고른다)
BACKUP_LINES=$(wc -l < "$BACKUP_FILE" 2>/dev/null | tr -d ' ')
BACKUP_BYTES=$(wc -c < "$BACKUP_FILE" 2>/dev/null | tr -d ' ')
if [ "${BACKUP_LINES:-0}" -gt 1200 ] || [ "${BACKUP_BYTES:-0}" -gt 262144 ]; then
    # 긴 세션 → 블록 병렬 압축 + merge verifier
    HANDOFF_CMD="/smart-handoff-parallel"
else
    # 짧은 세션 → 단일 스키마 압축
    HANDOFF_CMD="/smart-handoff"
fi
echo "HANDOFF: $HANDOFF_CMD (lines=$BACKUP_LINES bytes=$BACKUP_BYTES trigger=$TRIGGER)" >> "$DEBUG_LOG"

# 실행할 명령어
COMMAND="${HANDOFF_CMD} \"${BACKUP_FILE}\""

# 클립보드에 복사
echo -n "$COMMAND" | pbcopy

# 알림 표시
echo "Sending notification..." >> "$DEBUG_LOG"
osascript -e "display notification \"${HANDOFF_CMD} 복사됨 - 붙여넣기(⌘V) 후 실행\" with title \"📦 Compact 예정 (${TRIGGER})\" subtitle \"${SESSION_TITLE}\" sound name \"Submarine\"" 2>> "$DEBUG_LOG" &

echo "Done" >> "$DEBUG_LOG"
exit 0
