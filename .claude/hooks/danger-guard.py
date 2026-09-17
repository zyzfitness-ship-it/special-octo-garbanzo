#!/usr/bin/env python3
"""되돌릴 수 없는 명령과 머신 크리덴셜 접근에 대한 사전 게이트.

문제
----
CLAUDE.md 와 메모리에 이미 명문화된 규칙들이 **글로만 존재하고 강제되지 않았다.** 규칙을 읽고
지키는 주체가 매번 새로 시작하는 에이전트라, 사고는 규칙이 없어서가 아니라 규칙이 그 순간
읽히지 않아서 났다:

    2026-07-24  cmux close-surface 를 빈 인자로 호출 → 자기 Claude 세션이 닫힘
    2026-07-18  진단 중 cfprefsd kill → 바탕화면 아이콘 크기가 2배로
    (기록)      광범위 pkill 패턴 → 상시 pm2 서버까지 동반 종료

git 파괴 명령은 특히 사각지대였다. CLAUDE.md 의 파일 정리 규칙은 rm 을 금지하고 휴지통 이동 +
moves.csv 로그를 강제하는데, `git reset --hard` 는 커밋 안 된 작업을 즉시 없애면서 휴지통에도
안 남고 로그도 안 남긴다.

동작
----
    PreToolUse(Bash)              → 명령 문자열을 세그먼트로 쪼개 패턴 대조
    PreToolUse(Read|Edit|Write)   → 머신 크리덴셜 파일 접근 검사

    deny  = 정당한 사유가 없는 것 (~/.claude 삭제, 전역 데몬 kill, SSH 키 덮어쓰기)
    ask   = 정당할 수도 있는 것 (git reset --hard, 넓은 pkill, 크리덴셜 읽기)
    allow = 빌드 산출물 정리 등 일상 작업 (node_modules, dist, __pycache__ …)

PreToolUse 의 deny 는 --dangerously-skip-permissions 와 bypassPermissions 모드에서도 유효하다
(권한 모드 체크보다 먼저 발화). 승인 팝업을 끄고 쓰는 습관이 들면 사실상 여기가 유일하게
살아있는 방어층이 된다.

오탐을 줄이는 설계
-----------------
`rm -rf ./node_modules` 같은 정상 작업까지 막는 넓은 정규식은 쓰지 않는다. rm 은 **무엇을
지우는지**로 판단한다 — 빌드 산출물이면 통과, 실제 작업물이면 ask, ~/.claude 면 deny.

무인 세션
--------
CLAUDE_UNATTENDED=1 이 설정돼 있으면 차단하지 않고 로그만 남긴다. 사람이 없는 잡에서 ask 가
뜨면 잡이 조용히 멈추고 다음 감시 주기까지 아무도 모르기 때문이다. 이건 자동 판별이 아니라
**명시적 마커**다 — permission_mode 도 CLAUDE_CODE_ENTRYPOINT 도 대화형과 -p 모드를 구분하지
못한다는 걸 실측으로 확인했다(둘 다 각각 bypassPermissions / cli 로 동일).

로그: ~/.claude/logs/danger-guard.log
끄기: DANGER_GUARD_DISABLE=1
"""

import datetime as dt
import json
import os
import re
import shlex
import sys

HOME = os.path.expanduser("~")
LOG = os.path.join(HOME, ".claude", "logs", "danger-guard.log")

# rm 이 지워도 되는 것 — 재생성 가능한 산출물.
# 경로 '컴포넌트' 단위로 본다. `dist` 처럼 앞에 슬래시가 없는 형태를 놓치지 않기 위해서다.
DISPOSABLE_NAMES = {
    "node_modules", "__pycache__", ".next", ".nuxt", ".turbo", ".parcel-cache",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", ".cache", "dist", "build",
    "target", "coverage", "out", ".venv", "venv", ".DS_Store", ".svelte-kit",
}
DISPOSABLE_SUFFIX = (".pyc", ".pyo", ".egg-info", ".log", ".tmp")
DISPOSABLE_UNDER = ("/tmp/", "/scratchpad/", "/.Trash/", "/var/folders/")


def disposable(target):
    """이 경로가 '지워도 되는 산출물'인가."""
    t = os.path.expanduser(target.strip().strip("'\"").rstrip("/"))
    if any(u in t for u in DISPOSABLE_UNDER) or t.startswith("/tmp"):
        return True
    if t.endswith(DISPOSABLE_SUFFIX) or t.endswith("*.pyc"):
        return True
    parts = [p for p in t.replace("\\", "/").split("/") if p and p != "."]
    return bool(parts) and any(p in DISPOSABLE_NAMES for p in parts)

# CLAUDE.md: "홈 폴더의 ~/.claude 는 절대 변경/이동/삭제 금지".
# 다만 취지는 ~/.claude **자체**와 복구 불가능한 내용물을 지키는 것이지, 그 안의 모든 파일을
# 영구 동결하는 게 아니다. 로그·캐시는 재생성되므로 지워도 된다. 세 계층으로 나눈다.
CLAUDE_HOME = re.compile(
    r"(^|[\s'\"=])(~|\$HOME|/Users/[^/\s]+|/home/[^/\s]+)/\.claude(?P<rest>/\S*)?")

# 잃으면 복구가 안 되는 것 — 세션 기록은 이미 한 번 유실된 적이 있다(2025/11~2026/01)
IRREPLACEABLE = ("projects", "skills", "hooks", "plugins", "todos", "agents",
                 "commands", "settings.json", "settings.local.json", "CLAUDE.md",
                 "memory", "statusline.sh", "bin", "scripts")
# 재생성되는 것 — 막을 이유가 없다
REGENERABLE = ("logs", "shell-snapshots", "statsig", ".quality-gate",
               ".shared-guard", "__pycache__", ".gate-selftest")


def claude_home_verdict(seg):
    """~/.claude 대상 파괴 명령의 계층 판정.

    반환: None(이 규칙과 무관) · ("allow", …)(명시적 통과) · (deny|ask, 사유)
    "allow" 는 뒤따르는 일반 rm 규칙까지 건너뛴다 — 재생성되는 것을 지우겠다는 판단이
    일반 규칙에서 다시 뒤집히면 계층을 나눈 의미가 없다.
    """
    m = CLAUDE_HOME.search(seg)
    if not m:
        return None
    rest = (m.group("rest") or "").lstrip("/")
    if not rest:                                   # ~/.claude 자체
        return ("deny", "~/.claude 는 삭제·이동할 수 없습니다 (CLAUDE.md 절대 규칙). "
                        "세션 기록·설정·훅·스킬이 전부 들어 있습니다.")
    top = rest.split("/")[0]
    if top in REGENERABLE:
        return ("allow", "")                       # 로그·캐시 — 일상 정리
    if top in IRREPLACEABLE:
        return ("deny", f"~/.claude/{top} 은 복구할 수 없는 자산입니다 "
                        f"(CLAUDE.md: ~/.claude 변경·이동·삭제 금지). "
                        f"정말 필요하면 사용자가 직접 처리해야 합니다.")
    return ("ask", f"~/.claude/{top} 을 삭제·이동하려 합니다. "
                   f"Claude Code 설정 영역이라 영향 범위를 확인해 주세요.")

# 죽이면 시스템이 이상해지는 데몬 — 2026-07-18 cfprefsd 사고
GLOBAL_DAEMONS = re.compile(
    r"\b(pkill|killall|kill\s+-9)\b.*\b(cfprefsd|Finder|ControlCenter|SystemUIServer"
    r"|WindowServer|Dock|loginwindow|launchd|coreaudiod|mds|mdworker)\b"
)

GIT_DESTRUCTIVE = (
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "git reset --hard — 커밋 안 된 변경이 즉시 사라집니다"),
    (re.compile(r"\bgit\s+clean\s+-[a-z]*f"), "git clean -f — 추적되지 않는 파일이 삭제됩니다"),
    (re.compile(r"\bgit\s+checkout\s+(--\s|\.\s*$|\.\s)"), "git checkout -- <파일> — 로컬 수정이 버려집니다"),
    (re.compile(r"\bgit\s+restore\b(?!.*--staged)"), "git restore — 로컬 수정이 버려집니다"),
    (re.compile(r"\bgit\s+stash\s+(drop|clear)\b"), "git stash drop/clear — 보관해 둔 변경이 사라집니다"),
    (re.compile(r"\bgit\s+push\b.*(--force(?!-with-lease)|\s-f\b)"), "git push --force — 원격 히스토리를 덮어씁니다"),
    (re.compile(r"\bgit\s+branch\s+-D\b"), "git branch -D — 병합되지 않은 브랜치를 강제 삭제합니다"),
    (re.compile(r"\bgit\s+reflog\s+expire\b"), "git reflog expire — 복구 근거가 사라집니다"),
    (re.compile(r"\bgit\s+gc\b.*--prune"), "git gc --prune — 도달 불가 객체가 즉시 삭제됩니다"),
)

# 머신 단위 크리덴셜. 프로젝트 .env 는 여기 넣지 않는다 —
# 일상적으로 다루고, 배포 경계는 secret-scan.sh 가 이미 막는다.
CRED_CRITICAL = re.compile(r"/(\.ssh/(id_|.*_key)|\.gnupg/|\.aws/credentials|Library/Keychains/)")
CRED_ASK = re.compile(r"(\.pem|\.p12|\.pfx|\.keystore)$|/(\.netrc|\.npmrc)$")

SPLIT = re.compile(r"\s*(?:\|\||&&|\||;|\n)\s*")

# ⚠️ 인용부호 안은 쪼개면 안 된다. SPLIT 은 `\n` 도 구분자로 쓰는데, 여러 줄 인용 인자
# (`git commit -m "…\n  rm -rf / 가 deny…"`) 를 그대로 쪼개면 **메시지 본문의 한 줄이
# 독립 세그먼트가 되어 그 줄의 첫 단어가 '명령어 자리'로 오인된다**. 실제로 이 가드의
# 수정 내역을 적은 커밋 메시지가 자기 자신에게 막혔다(2026-07-30).
# '언급 vs 실행' 구분(위 주석)은 인용 안을 보호해야 비로소 성립한다.
def split_segments(cmd):
    """셸 구분자로 쪼갠다. 단 ' " ` 안과 백슬래시 이스케이프는 건너뛴다."""
    segs, buf, quote, i = [], [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(cmd):
                buf.append(cmd[i + 1]); i += 2; continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"`":
            quote = ch; buf.append(ch); i += 1; continue
        if ch == "\\" and i + 1 < len(cmd):
            buf.append(ch); buf.append(cmd[i + 1]); i += 2; continue
        two = cmd[i:i + 2]
        if two in ("||", "&&"):
            segs.append("".join(buf)); buf = []; i += 2; continue
        if ch in "|;\n":
            segs.append("".join(buf)); buf = []; i += 1; continue
        buf.append(ch); i += 1
    segs.append("".join(buf))
    return segs

# 명령을 '언급'하는 것과 '실행'하는 것은 다르다.
#   echo "rm -rf ~/.claude"     ← 문서에 적는 행위. 막으면 안 된다.
#   grep -r "git reset --hard"  ← 검색. 막으면 안 된다.
# 그래서 위험 패턴을 세그먼트 아무 데서나 찾지 않고, **그 세그먼트의 명령어 자리**를 본다.
# (xargs rm 처럼 한 겹 감싸면 빠져나간다. 이 가드는 흔한 사고를 막는 과속방지턱이지
#  샌드박스가 아니다 — 강한 경계가 필요하면 permissions.deny 를 쓴다.)
WRAPPERS = {"sudo", "command", "env", "time", "nohup", "exec", "builtin", "\\"}


def command_of(seg):
    """세그먼트의 (명령어, 인자목록). 판정 불가면 (None, [])."""
    try:
        toks = shlex.split(seg, comments=True)
    except ValueError:                    # 따옴표가 안 맞는 등 — 대충이라도 쪼갠다
        toks = seg.split()
    while toks:
        t = toks[0]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", t) or t in WRAPPERS:
            toks = toks[1:]
            continue
        break
    if not toks:
        return None, []
    return os.path.basename(toks[0]), toks[1:]


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as fh:
            fh.write(f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass


def decide(decision, reason):
    """PreToolUse 결정을 JSON 으로 낸다. exit 0 + JSON — exit code 와 섞지 않는다."""
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


# 리다이렉션은 삭제 대상이 아니다. `rm -rf /tmp/x 2>/dev/null` 의 `2>/dev/null` 을 타겟으로
# 세면 disposable() 전수 통과가 깨져 tmp 정리까지 ask 로 튄다(2026-07-30 실측).
REDIR = re.compile(r"^(?:\d*[<>]&?\d*|&>>?)")

# `SM=/tmp/x` 처럼 앞에서 정의한 변수를 rm 이 `"$SM"` 으로 받는 패턴이 흔하다. 변수를 그대로
# 두면 disposable() 이 판정할 수 없어 역시 ask 로 튄다. 리터럴 대입만 해석한다 —
# 명령치환($(...))·산술 등은 건드리지 않고 미해석으로 남겨 ask 를 유지한다(fail-safe).
ASSIGN = re.compile(r"(?:^|[\s;&|])([A-Za-z_][A-Za-z0-9_]*)=([^\s;&|<>()`$]+)")
VARREF = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


def strip_redirections(args):
    """인자 목록에서 리다이렉션 토큰과 그 대상 파일을 걷어낸다."""
    out, skip_next = [], False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if REDIR.match(a):
            # `2>/dev/null` 처럼 붙어 있으면 이 토큰만, `> out.txt` 처럼 떨어져 있으면 다음 토큰까지
            if re.fullmatch(r"\d*[<>]&?\d*|&>>?", a):
                skip_next = True
            continue
        out.append(a)
    return out


def resolve_vars(targets, full_cmd):
    """전체 명령에서 리터럴 변수 대입을 모아 타겟의 $VAR 를 치환한다. 못 풀면 원본 유지."""
    # $HOME 은 대입문이 아니라 환경변수라 스캔에 안 잡힌다. 뜻이 명확하므로 미리 채워 둔다
    # (그래야 `rm -rf $HOME` 이 ask 가 아니라 deny 로 잡힌다). $PWD 처럼 실행 시점에 달라지는
    # 것은 넣지 않는다 — 잘못 단정하면 오히려 위험하다.
    env = {"HOME": HOME}
    env.update({k: v.strip("'\"") for k, v in ASSIGN.findall(full_cmd or "")})
    resolved = []
    for t in targets:
        for _ in range(3):                # 변수가 변수를 참조하는 얕은 중첩까지만
            new = VARREF.sub(lambda m: env.get(m.group(1), m.group(0)), t)
            if new == t:
                break
            t = new
        resolved.append(t)
    return resolved


def check_rm(seg, args, full_cmd=None):
    """rm 은 '무엇을 지우는가'로 판단한다."""
    v = claude_home_verdict(seg)
    if v:
        return None if v[0] == "allow" else v
    targets = [t for t in strip_redirections(args) if not t.startswith("-")]
    targets = resolve_vars(targets, full_cmd)
    # `"/".rstrip("/")` 은 빈 문자열이 되므로 루트를 비교 대상에 넣어도 매칭되지 않았다
    # → `rm -rf /` 가 deny 가 아니라 ask 로 떨어지던 버그. 빈 결과는 루트로 되돌린다.
    def norm_root(t):
        p = os.path.expanduser(t.strip().strip("'\"")).rstrip("/")
        return p or "/"
    if any(norm_root(t) in ("/", os.path.expanduser("~")) for t in targets):
        return ("deny", "홈 또는 루트 전체를 삭제하려는 명령입니다.")
    if not targets:
        return None
    if all(disposable(t) for t in targets):
        return None                      # 빌드 산출물 정리 — 일상 작업
    return ("ask", "rm 으로 직접 삭제하려 합니다. CLAUDE.md 규칙은 휴지통 이동 + "
                   "moves.csv 로그를 요구합니다. 복구 불가한 삭제가 맞는지 확인해 주세요.\n"
                   f"  대상: {' '.join(targets[:5])}")


def check_bash(cmd):
    for seg in split_segments(cmd):     # 인용부호 안은 쪼개지 않는다 (위 주석 참조)
        seg = seg.strip()
        if not seg:
            continue
        name, args = command_of(seg)
        if not name:
            continue

        if name == "rm":
            r = check_rm(seg, args, cmd)   # 변수 해석을 위해 전체 명령을 함께 넘긴다
            if r:
                return r

        elif name == "mv":
            v = claude_home_verdict(seg)
            if v and v[0] != "allow":
                return v

        elif name in ("pkill", "killall", "kill"):
            if GLOBAL_DAEMONS.search(seg):
                return ("deny", "전역 데몬을 종료하려 합니다. 2026-07-18 에 cfprefsd 를 죽였다가 "
                                "바탕화면 아이콘 크기가 2배로 바뀐 사고가 있었습니다. "
                                "진단은 대상 앱 범위로만 하세요.")
            # 포트 기준이 아닌 광범위 프로세스 종료
            if name in ("pkill", "killall"):
                pat = [a for a in args if not a.startswith("-")]
                if not pat or len(pat[0]) < 6:
                    return ("ask", "패턴이 넓은 프로세스 종료입니다. 상시 pm2 서버까지 같이 죽은 "
                                   "전례가 있습니다. 포트 기준을 권합니다: "
                                   "lsof -ti:<PORT> | xargs kill")

        elif name == "git":
            for pat, why in GIT_DESTRUCTIVE:
                if pat.search(seg):
                    return ("ask", f"{why}\n  되돌릴 수 없습니다. 실행할까요?")

        elif name == "cmux" and "close-surface" in args:
            m = re.search(r"--surface\s+(\S+)", seg)
            if not m or m.group(1) in ('""', "''", "$S", "${S}"):
                return ("deny", "cmux close-surface 를 인자 없이(또는 빈 값으로) 호출하면 "
                                "포커스된 서피스 — 즉 이 Claude 세션 터미널 — 이 닫힙니다 "
                                "(2026-07-24 실제 사고). 가드 래퍼를 쓰세요: "
                                "python3 ~/.claude/scripts/cmux-close-tab.py <surface:N>")

        elif name in ("curl", "scp", "rsync", "nc") and CRED_CRITICAL.search(seg):
            return ("deny", "크리덴셜 파일을 외부로 전송하려는 명령으로 보입니다.")

        if re.search(r"\bDROP\s+(TABLE|DATABASE)\b|\bTRUNCATE\s+TABLE\b", seg, re.I) \
                and name in ("psql", "mysql", "sqlite3", "mongo", "mongosh"):
            return ("ask", "데이터베이스 파괴 명령입니다. 되돌릴 수 없습니다.")

    return None


def check_file(tool_name, path):
    if CRED_CRITICAL.search(path):
        if tool_name in ("Write", "Edit", "NotebookEdit"):
            return ("deny", f"{path} 는 머신 크리덴셜입니다. 덮어쓰면 SSH·클라우드 접근이 "
                            "끊기고 복구가 어렵습니다.")
        return ("ask", f"{path} 는 머신 크리덴셜입니다. 내용이 대화 컨텍스트로 들어옵니다. "
                       "정말 필요한가요?")
    if CRED_ASK.search(path) and tool_name in ("Write", "Edit"):
        return ("ask", f"{path} 는 인증 정보 파일입니다. 수정할까요?")
    return None


def main():
    if os.environ.get("DANGER_GUARD_DISABLE"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_name = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}

    if tool_name == "Bash":
        verdict = check_bash(ti.get("command") or "")
    elif tool_name in ("Read", "Write", "Edit", "NotebookEdit"):
        raw = ti.get("file_path") or ""
        verdict = check_file(tool_name, os.path.realpath(os.path.expanduser(raw))) if raw else None
    else:
        return 0

    if not verdict:
        return 0

    decision, reason = verdict
    where = (ti.get("command") or ti.get("file_path") or "")[:160]

    # 무인 세션에서는 막지 않는다 — 사람이 승인해 줄 수 없고, 멈추면 아무도 모른다
    if os.environ.get("CLAUDE_UNATTENDED"):
        log(f"UNATTENDED-PASS[{decision}] {tool_name} :: {where}")
        return 0

    log(f"{decision.upper()} {tool_name} :: {where}")
    return decide(decision, f"[danger-guard] {reason}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:        # 가드 버그가 모든 작업을 막아선 안 된다
        log(f"훅 예외(통과 처리): {exc}")
        sys.exit(0)
