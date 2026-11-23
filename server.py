import os
import json
import uuid
import datetime
import hashlib
import secrets
import urllib.request
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

env_paths = [
    BASE_DIR / ".env",
    BASE_DIR.parent / "my-gemini-chat" / ".env",
]

for p in env_paths:
    if p.exists():
        load_dotenv(p)
        break

api_key = os.getenv("GEMINI_API_KEY")
model_name = os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

def check_supabase_config():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        missing = []
        if not SUPABASE_URL:
            missing.append("SUPABASE_URL")
        if not SUPABASE_SERVICE_ROLE_KEY:
            missing.append("SUPABASE_SERVICE_ROLE_KEY")
        return False, f"Supabase 환경 변수가 설정되지 않았습니다: {', '.join(missing)} (.env 파일을 확인해주세요)"
    return True, ""

def supabase_request(table: str, method: str = "GET", params: dict = None, body=None, headers_extra: dict = None):
    ok, err = check_supabase_config()
    if not ok:
        raise Exception(err)

    query_str = ""
    if params:
        query_str = "?" + urllib.parse.urlencode(params)

    url = f"{SUPABASE_URL}/rest/v1/{table}{query_str}"
    data_bytes = json.dumps(body).encode("utf-8") if body is not None else None

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    if headers_extra:
        headers.update(headers_extra)

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode("utf-8")
            if resp_body:
                return json.loads(resp_body)
            return None
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        raise Exception(f"Supabase HTTP {e.code} 오류 ({table}): {err_msg}")
    except Exception as e:
        raise Exception(f"Supabase 연결 오류 ({table}): {str(e)}")

# 비밀번호 PBKDF2-HMAC-SHA256 해싱 및 검증
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return f"pbkdf2_sha256$100000${salt}${dk.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    try:
        parts = hashed.split("$")
        if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
            iterations = int(parts[1])
            salt = parts[2]
            stored_hash = parts[3]
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
            return secrets.compare_digest(dk.hex(), stored_hash)
        elif hashed == password:
            return True
        return False
    except Exception:
        return False

SYSTEM_INSTRUCTION = """
당신은 데이터센터 인프라 및 서버 룸 운영을 총괄하는 숙련된 시니어 DCO(Data Center Operations) 엔지니어 어시스턴트이자, 본 DCO 교육 대시보드 웹의 스마트 AI 비서입니다.
사용자는 AWS DCO 양성과정 수강생 또는 데이터센터 초보 엔지니어입니다.

[행동 지침]
1. 일반 질의: 데이터센터 인프라(랙/서버 설치, 광케이블링, 쿨링/공조, 전력 PDU/UPS, 리눅스 장애 대응 등) 질문에는 전문적이고 친절하며 안전 수칙을 최우선으로 간결·명확하게 한국어로 답변하세요.
2. 웹 기능 요청: 사용자가 시간표 확인, 메모/리마인더 작성/조회/삭제, 퀴즈 출제/풀기, 지식 카드 보기, 진도율 확인, 테마 변경, 아키텍처 보기 등 웹 대시보드 기능 실행을 원하면 설명 텍스트 대신 반드시 적절한 Function Call(도구)을 호출하세요.
"""

# Gemini 툴 선언 (웹 기능 연동 Tool Calling)
DCO_WEB_TOOLS = [
    {
        "functionDeclarations": [
            {
                "name": "show_today_schedule",
                "description": "오늘의 교육 시간표와 오전/오후 수업 일정 및 배정 강의실을 화면에 표시하고 안내합니다.",
                "parameters": {"type": "OBJECT", "properties": {}}
            },
            {
                "name": "show_tomorrow_schedule",
                "description": "내일 또는 다음 수업일의 교육 시간표와 수업 일정을 화면에 표시합니다.",
                "parameters": {"type": "OBJECT", "properties": {}}
            },
            {
                "name": "show_full_schedule",
                "description": "1~6주차 전체 종합 시간표를 화면에 펼쳐서 보여줍니다. 특정 주차(week_num: 1~6)를 지정할 수도 있습니다.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "week_num": {
                            "type": "INTEGER",
                            "description": "조회할 주차 번호 (1부터 6까지의 정수, 생략 시 현재 주차)"
                        }
                    }
                }
            },
            {
                "name": "show_subject_book_info",
                "description": "특정 과목의 공식 등록 교재, 저자, 배정 강의실 안내 팝업을 화면에 띄웁니다.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "subject_name": {
                            "type": "STRING",
                            "description": "과목명 (예: Datacenter Overview, Computer Hardware, Network Fundamentals, Operating Systems, Routing and Switching, Optical Communication, Scripting and Automation, 생성형AI 활용)"
                        }
                    },
                    "required": ["subject_name"]
                }
            },
            {
                "name": "create_user_memo",
                "description": "사용자의 나만의 리마인더에 새로운 메모를 작성하여 안전하게 저장하고 메모 탭으로 이동합니다.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "text": {
                            "type": "STRING",
                            "description": "작성하여 저장할 메모 본문 내용"
                        }
                    },
                    "required": ["text"]
                }
            },
            {
                "name": "list_user_memos",
                "description": "사용자가 현재까지 작성해 둔 리마인더 메모 목록을 조회하여 화면에 보여줍니다.",
                "parameters": {"type": "OBJECT", "properties": {}}
            },
            {
                "name": "request_delete_memo",
                "description": "사용자가 특정 메모의 삭제를 요청할 때 호출합니다. 안전을 위해 사용자에게 삭제 확인(Confirm) 절차를 진행합니다.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "memo_keyword": {
                            "type": "STRING",
                            "description": "삭제하고자 하는 메모의 핵심 키워드 또는 내용"
                        }
                    },
                    "required": ["memo_keyword"]
                }
            },
            {
                "name": "start_quiz",
                "description": "실무 퀴즈 탭으로 화면을 전환하여 문제를 풀 수 있도록 하거나, 새로운 AI 퀴즈를 즉시 출제합니다.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "generate_new": {
                            "type": "BOOLEAN",
                            "description": "새로운 AI 실무 문제를 새로 생성할지 여부 (기본 false)"
                        }
                    }
                }
            },
            {
                "name": "show_knowledge_card",
                "description": "핵심 실무 지식 카드 탭으로 화면을 전환하여 현장 팁을 학습할 수 있도록 합니다.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "generate_new": {
                            "type": "BOOLEAN",
                            "description": "새로운 AI 지식 카드를 새로 생성할지 여부 (기본 false)"
                        }
                    }
                }
            },
            {
                "name": "show_progress_status",
                "description": "전체 교육 총 진도율(%)과 총 이수 시간, 잔여 시간 현황을 안내하고 진도율 카드 영역을 보여줍니다.",
                "parameters": {"type": "OBJECT", "properties": {}}
            },
            {
                "name": "switch_hub_tab",
                "description": "우측 실무 트레이닝 허브의 특정 탭(지식카드, 퀴즈, 메모, 아키텍처)으로 화면을 전환합니다.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "tab_name": {
                            "type": "STRING",
                            "description": "전환할 탭 이름 ('card': 핵심지식, 'quiz': 실무퀴즈, 'memo': 메모/리마인더, 'arch': 프로젝트 아키텍처)"
                        }
                    },
                    "required": ["tab_name"]
                }
            },
            {
                "name": "toggle_dashboard_theme",
                "description": "대시보드 화면의 테마를 다크 모드 또는 라이트 모드로 전환합니다.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "theme": {
                            "type": "STRING",
                            "description": "원하는 테마 ('dark', 'light', 또는 'toggle')"
                        }
                    }
                }
            },
            {
                "name": "generate_memo_quiz",
                "description": "사용자가 작성한 학습 메모를 바탕으로 맞춤 퀴즈를 출제합니다. 과목(subject)이나 문제 수(count)가 주어지면 반영합니다.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "subject": {
                            "type": "STRING",
                            "description": "퀴즈 대상 과목 (예: '네트워크', '서버', '리눅스', '전체' 등. 기본값: '전체')"
                        },
                        "count": {
                            "type": "INTEGER",
                            "description": "생성할 문제 수 (기본값: 1, 최대: 3)"
                        }
                    }
                }
            }
        ]
    }
]

CANDIDATE_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
    "gemini-3.8-flash"
]

def get_today_str():
    return datetime.datetime.now().strftime("%Y-%m-%d")

def check_and_increment_daily_usage(username):
    ok, err = check_supabase_config()
    if not ok:
        return False, err, 0, 5

    try:
        users = supabase_request("user_accounts", "GET", {"username": f"eq.{username}", "select": "*"})
        if not users:
            return False, "인증되지 않은 사용자입니다. 로그인 후 이용해주세요.", 0, 5
        user = users[0]

        is_admin = (user.get("role") == "admin")
        max_limit = 9999 if is_admin else 5
        today = get_today_str()

        usage_records = supabase_request("api_daily_usage", "GET", {
            "username": f"eq.{username}",
            "usage_date": f"eq.{today}",
            "select": "*"
        })

        current_count = usage_records[0].get("call_count", 0) if usage_records else 0

        if not is_admin and current_count >= 5:
            return False, "오늘 API 일일 호출 한도(5회)를 모두 소진하셨습니다. (내일 0시에 초기화됩니다)", current_count, 5

        new_count = current_count + 1
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        supabase_request(
            "api_daily_usage",
            "POST",
            body={
                "username": username,
                "usage_date": today,
                "call_count": new_count,
                "last_called_at": now_iso
            },
            headers_extra={"Prefer": "resolution=merge-duplicates,return=representation"}
        )

        return True, "", new_count, max_limit
    except Exception as e:
        return False, f"사용량 확인 중 오류가 발생했습니다: {str(e)}", 0, 5

def log_activity(username, action, details="", is_api=False, extra=None):
    try:
        name = "익명/게스트"
        role = "guest"
        if username and username != "anonymous":
            try:
                users = supabase_request("user_accounts", "GET", {"username": f"eq.{username}", "select": "name,role"})
                if users:
                    name = users[0].get("name", username)
                    role = users[0].get("role", "user")
            except Exception:
                pass

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            "id": str(uuid.uuid4())[:8],
            "username": username or "익명",
            "name": name,
            "role": role,
            "action": action,
            "details": details,
            "is_api": is_api,
            "extra": extra,
            "timestamp": now_str
        }
        supabase_request("user_activity_logs", "POST", body=log_entry)
    except Exception as e:
        print(f"[log_activity error] {e}")

def get_current_user(token):
    if not token:
        return None
    try:
        users = supabase_request("user_accounts", "GET", {"session_token": f"eq.{token}", "select": "*"})
        if users:
            return users[0]
    except Exception as e:
        print(f"[get_current_user error] {e}")
    return None

def generate_gemini(prompt_text, system_instruction=None, tools=None):
    if not api_key:
        raise Exception(".env 파일에 GEMINI_API_KEY가 설정되지 않았습니다.")
    
    last_error = None
    for model in CANDIDATE_MODELS:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt_text}]}],
                "generationConfig": {"temperature": 0.7}
            }
            if system_instruction:
                payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
            if tools:
                payload["tools"] = tools

            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=25) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                candidates = res_data.get("candidates", [{}])
                parts = candidates[0].get("content", {}).get("parts", [{}])
                first_part = parts[0] if parts else {}
                
                # Tool call (functionCall) 발생 시
                if "functionCall" in first_part:
                    return {
                        "type": "function_call",
                        "function_call": first_part["functionCall"]
                    }
                
                # 일반 텍스트 응답
                raw_text = first_part.get("text", "")
                cleaned = raw_text.replace("```json", "").replace("```", "").strip()
                if tools is None:
                    return cleaned
                return {
                    "type": "text",
                    "text": cleaned
                }
        except urllib.error.HTTPError as e:
            last_error = e
            continue
        except Exception as e:
            last_error = e
            continue

    raise Exception(f"Gemini API 오류 ({last_error})")

class DCODashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def get_token_from_header(self):
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:].strip()
        return None

    def do_GET(self):
        # 1. 관리자용 전체 사용량 및 로그 조회
        if self.path == "/api/admin/usage":
            token = self.get_token_from_header()
            user = get_current_user(token)
            if not user or user.get("role") != "admin":
                self.send_json_error(403, "관리자 권한이 필요합니다.")
                return

            try:
                today = get_today_str()
                all_users = supabase_request("user_accounts", "GET", {"select": "username,name,role,created_at"}) or []
                all_usages = supabase_request("api_daily_usage", "GET", {"select": "username,usage_date,call_count"}) or []
                recent_logs = supabase_request("user_activity_logs", "GET", {
                    "select": "*",
                    "order": "created_at.desc",
                    "limit": "200"
                }) or []

                today_usage_map = {}
                total_usage_map = {}
                for u in all_usages:
                    un = u.get("username")
                    cnt = u.get("call_count", 0)
                    total_usage_map[un] = total_usage_map.get(un, 0) + cnt
                    if u.get("usage_date") == today:
                        today_usage_map[un] = cnt

                users_list = []
                for u in all_users:
                    un = u.get("username")
                    users_list.append({
                        "username": un,
                        "name": u.get("name", un),
                        "role": u.get("role", "user"),
                        "api_usage": total_usage_map.get(un, 0),
                        "today_usage": today_usage_map.get(un, 0),
                        "created_at": u.get("created_at", "-")
                    })

                self.send_json({
                    "users": users_list,
                    "logs": recent_logs,
                    "all_user_data": {}
                })
            except Exception as e:
                self.send_json_error(500, f"관리자 데이터 조회 오류: {str(e)}")
            return

        # 2. 내 정보 조회 (일일 남은 횟수 포함)
        elif self.path == "/api/auth/me":
            token = self.get_token_from_header()
            user = get_current_user(token)
            if not user:
                self.send_json_error(401, "인증되지 않은 사용자입니다.")
                return

            try:
                today = get_today_str()
                username = user["username"]
                today_record = supabase_request("api_daily_usage", "GET", {
                    "username": f"eq.{username}",
                    "usage_date": f"eq.{today}",
                    "select": "call_count"
                })
                today_used = today_record[0]["call_count"] if today_record else 0

                all_user_usages = supabase_request("api_daily_usage", "GET", {
                    "username": f"eq.{username}",
                    "select": "call_count"
                }) or []
                total_api_used = sum(item.get("call_count", 0) for item in all_user_usages)

                max_limit = 9999 if user.get("role") == "admin" else 5
                self.send_json({
                    "username": user["username"],
                    "name": user["name"],
                    "role": user["role"],
                    "api_usage": total_api_used,
                    "today_usage": today_used,
                    "daily_limit": max_limit
                })
            except Exception as e:
                self.send_json_error(500, f"내 정보 조회 오류: {str(e)}")
            return

        # 3. 로그인한 유저의 개인 저장 데이터 조회 (메모, 생성된 지식카드, 생성된 퀴즈, 챗봇 기록)
        elif self.path == "/api/user/data":
            token = self.get_token_from_header()
            user = get_current_user(token)
            if not user:
                self.send_json_error(401, "로그인이 필요한 서비스입니다.")
                return

            try:
                username = user["username"]
                # 1) memos
                raw_memos = supabase_request("user_memos", "GET", {
                    "username": f"eq.{username}",
                    "select": "id,text,date,subject",
                    "order": "created_at.desc"
                }) or []
                memos = []
                for m in raw_memos:
                    memos.append({
                        "id": m.get("id"),
                        "text": m.get("text"),
                        "date": m.get("date"),
                        "subject": m.get("subject", "학습 메모")
                    })

                # 2) cards
                raw_cards = supabase_request("user_knowledge_cards", "GET", {
                    "username": f"eq.{username}",
                    "select": "data",
                    "order": "created_at.asc"
                }) or []
                cards = [c["data"] for c in raw_cards if "data" in c]

                # 3) quizzes
                raw_quizzes = supabase_request("user_quizzes", "GET", {
                    "username": f"eq.{username}",
                    "select": "data",
                    "order": "created_at.asc"
                }) or []
                quizzes = [q["data"] for q in raw_quizzes if "data" in q]

                # 4) chat
                raw_chat = supabase_request("user_chat_logs", "GET", {
                    "username": f"eq.{username}",
                    "select": "id,question,reply,timestamp",
                    "order": "created_at.asc"
                }) or []
                chat = []
                for c in raw_chat:
                    chat.append({
                        "id": c.get("id"),
                        "question": c.get("question"),
                        "reply": c.get("reply"),
                        "timestamp": c.get("timestamp")
                    })

                self.send_json({
                    "memos": memos,
                    "cards": cards,
                    "quizzes": quizzes,
                    "chat": chat
                })
            except Exception as e:
                self.send_json_error(500, f"사용자 데이터 조회 오류: {str(e)}")
            return

        # 4. GitHub 최신 커밋 패치 내역 조회 (프록시 & 토큰 보안 관리)
        elif self.path == "/api/git-patches":
            try:
                gh_token = os.getenv("GITHUB_TOKEN", "").strip()
                gh_url = "https://api.github.com/repos/pghpgh0136/dco-dashboard/commits?sha=main&per_page=15"
                headers = {
                    "User-Agent": "DCO-Dashboard-App",
                    "Accept": "application/vnd.github.v3+json"
                }
                if gh_token:
                    headers["Authorization"] = f"Bearer {gh_token}"

                req = urllib.request.Request(gh_url, headers=headers)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    raw_commits = json.loads(resp.read().decode("utf-8"))

                patches = []
                for c in raw_commits:
                    sha_short = c.get("sha", "")[:7]
                    commit_obj = c.get("commit", {})
                    author_obj = commit_obj.get("author", {})
                    author_name = author_obj.get("name", "pghpgh0136")
                    raw_date = author_obj.get("date", "")
                    date_str = raw_date[:10] if len(raw_date) >= 10 else "-"
                    full_msg = commit_obj.get("message", "").strip()
                    first_line = full_msg.split("\n")[0].strip()

                    tag = "Update"
                    title = first_line
                    if ":" in first_line:
                        prefix, rest = first_line.split(":", 1)
                        p_lower = prefix.strip().lower()
                        if "feat" in p_lower:
                            tag = "Feat"
                        elif "fix" in p_lower:
                            tag = "Fix"
                        elif "docs" in p_lower:
                            tag = "Docs"
                        elif "style" in p_lower or "design" in p_lower:
                            tag = "Style"
                        elif "deploy" in p_lower:
                            tag = "Deploy"
                        elif "init" in p_lower:
                            tag = "Init"
                        title = rest.strip()

                    body_lines = [l.strip() for l in full_msg.split("\n")[1:] if l.strip()]
                    desc = " ".join(body_lines) if body_lines else first_line

                    patches.append({
                        "hash": sha_short,
                        "date": date_str,
                        "tag": tag,
                        "title": title,
                        "desc": desc,
                        "author": author_name
                    })

                self.send_json({"success": True, "patches": patches})
            except Exception as e:
                self.send_json_error(500, f"GitHub 커밋 조회 오류: {str(e)}")
            return

        super().do_GET()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}

        token = self.get_token_from_header()
        user = get_current_user(token)
        username = user["username"] if user else (req_data.get("username") or "anonymous")

        # 0-1) 로그인
        if self.path == "/api/auth/login":
            u_name = req_data.get("username", "").strip()
            u_pass = req_data.get("password", "").strip()
            if not u_name or not u_pass:
                self.send_json_error(400, "아이디와 비밀번호를 모두 입력해주세요.")
                return

            try:
                users = supabase_request("user_accounts", "GET", {"username": f"eq.{u_name}", "select": "*"})
                if users and verify_password(u_pass, users[0].get("password_hash", "")):
                    user_info = users[0]
                    new_token = secrets.token_urlsafe(32)
                    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

                    supabase_request(
                        "user_accounts",
                        "PATCH",
                        params={"username": f"eq.{u_name}"},
                        body={"session_token": new_token, "last_login_at": now_iso}
                    )

                    today = get_today_str()
                    usage_rec = supabase_request("api_daily_usage", "GET", {
                        "username": f"eq.{u_name}",
                        "usage_date": f"eq.{today}",
                        "select": "call_count"
                    })
                    today_used = usage_rec[0]["call_count"] if usage_rec else 0

                    all_usages = supabase_request("api_daily_usage", "GET", {
                        "username": f"eq.{u_name}",
                        "select": "call_count"
                    }) or []
                    total_used = sum(item.get("call_count", 0) for item in all_usages)

                    max_limit = 9999 if user_info.get("role") == "admin" else 5

                    log_activity(u_name, "로그인", f"로그인 성공 (IP: {self.client_address[0]})", is_api=False)
                    self.send_json({
                        "token": new_token,
                        "user": {
                            "username": user_info["username"],
                            "name": user_info.get("name", user_info["username"]),
                            "role": user_info.get("role", "user"),
                            "api_usage": total_used,
                            "today_usage": today_used,
                            "daily_limit": max_limit
                        }
                    })
                else:
                    self.send_json_error(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
            except Exception as e:
                self.send_json_error(500, f"로그인 처리 중 오류: {str(e)}")
            return

        # 0-2) 로그아웃
        elif self.path == "/api/auth/logout":
            if token and user:
                try:
                    supabase_request(
                        "user_accounts",
                        "PATCH",
                        params={"username": f"eq.{user['username']}"},
                        body={"session_token": None}
                    )
                    log_activity(user["username"], "로그아웃", "로그아웃 완료", is_api=False)
                except Exception as e:
                    print(f"[logout error] {e}")
            self.send_json({"success": True})
            return

        # 0-3) 회원가입
        elif self.path == "/api/auth/register":
            u_name = req_data.get("username", "").strip()
            u_pass = req_data.get("password", "").strip()
            u_display = req_data.get("name", "").strip() or u_name
            if not u_name or not u_pass:
                self.send_json_error(400, "아이디와 비밀번호를 모두 입력해주세요.")
                return
            if len(u_name) < 3:
                self.send_json_error(400, "아이디는 최소 3자 이상이어야 합니다.")
                return

            try:
                existing = supabase_request("user_accounts", "GET", {"username": f"eq.{u_name}", "select": "username"})
                if existing:
                    self.send_json_error(400, "이미 존재하는 아이디입니다.")
                    return

                new_token = secrets.token_urlsafe(32)
                hashed_pass = hash_password(u_pass)
                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

                # 신규 회원은 기본적으로 role='user'
                new_user_data = {
                    "username": u_name,
                    "password_hash": hashed_pass,
                    "name": u_display,
                    "role": "user",
                    "session_token": new_token,
                    "created_at": now_iso,
                    "last_login_at": now_iso
                }
                supabase_request("user_accounts", "POST", body=new_user_data)

                log_activity(u_name, "회원가입", "신규 회원가입 및 자동 로그인", is_api=False)
                self.send_json({
                    "token": new_token,
                    "user": {
                        "username": u_name,
                        "name": u_display,
                        "role": "user",
                        "api_usage": 0,
                        "today_usage": 0,
                        "daily_limit": 5
                    }
                })
            except Exception as e:
                self.send_json_error(500, f"회원가입 처리 중 오류: {str(e)}")
            return

        # 0-4) 유저 개인 데이터 동기화 (메모 저장/삭제 등)
        elif self.path == "/api/user/save-data":
            if not user:
                self.send_json_error(401, "로그인이 필요한 서비스입니다.")
                return
            data_type = req_data.get("type")  # memos, cards, quizzes, chat
            items = req_data.get("items")
            if data_type in ["memos", "cards", "quizzes", "chat"] and items is not None:
                try:
                    un = user["username"]
                    if data_type == "memos":
                        supabase_request("user_memos", "DELETE", params={"username": f"eq.{un}"})
                        if items:
                            memo_rows = []
                            for m in items:
                                memo_rows.append({
                                    "username": un,
                                    "id": int(m.get("id")),
                                    "text": str(m.get("text", "")),
                                    "date": str(m.get("date", "")),
                                    "subject": str(m.get("subject", "학습 메모"))
                                })
                            supabase_request("user_memos", "POST", body=memo_rows)

                    elif data_type == "cards":
                        supabase_request("user_knowledge_cards", "DELETE", params={"username": f"eq.{un}"})
                        if items:
                            card_rows = []
                            for c in items:
                                c_id = str(c.get("id") or uuid.uuid4().hex[:8])
                                card_rows.append({
                                    "username": un,
                                    "id": c_id,
                                    "data": c
                                })
                            supabase_request("user_knowledge_cards", "POST", body=card_rows)

                    elif data_type == "quizzes":
                        supabase_request("user_quizzes", "DELETE", params={"username": f"eq.{un}"})
                        if items:
                            quiz_rows = []
                            for q in items:
                                q_id = str(q.get("id") or uuid.uuid4().hex[:8])
                                quiz_rows.append({
                                    "username": un,
                                    "id": q_id,
                                    "data": q
                                })
                            supabase_request("user_quizzes", "POST", body=quiz_rows)

                    elif data_type == "chat":
                        supabase_request("user_chat_logs", "DELETE", params={"username": f"eq.{un}"})
                        if items:
                            chat_rows = []
                            for ch in items:
                                ch_id = str(ch.get("id") or uuid.uuid4().hex[:8])
                                chat_rows.append({
                                    "username": un,
                                    "id": ch_id,
                                    "question": str(ch.get("question", "")),
                                    "reply": str(ch.get("reply", "")),
                                    "timestamp": str(ch.get("timestamp", ""))
                                })
                            supabase_request("user_chat_logs", "POST", body=chat_rows)

                    self.send_json({"success": True})
                except Exception as e:
                    self.send_json_error(500, f"데이터 동기화 오류: {str(e)}")
            else:
                self.send_json_error(400, "잘못된 데이터 형식입니다.")
            return

        # 0-5) 기능 사용 일반 로깅
        elif self.path == "/api/log-action":
            action = req_data.get("action", "기능 사용")
            details = req_data.get("details", "")
            extra = req_data.get("extra")
            log_activity(username, action, details, is_api=False, extra=extra)
            self.send_json({"success": True})
            return

        # 1) AI 챗봇 (가입 유저만 + 하루 5회 제한)
        elif self.path == "/api/chat":
            if not user:
                self.send_json_error(401, "비회원은 AI 챗봇을 이용할 수 없습니다. 로그인 후 이용해주세요.")
                return

            ok, err_msg, used_count, limit = check_and_increment_daily_usage(user["username"])
            if not ok:
                self.send_json_error(429, err_msg)
                return

            user_msg = req_data.get("message", "").strip()
            if not user_msg:
                self.send_json_error(400, "질문 내용을 입력해 주세요.")
                return
            try:
                chat_res = generate_gemini(user_msg, SYSTEM_INSTRUCTION, tools=DCO_WEB_TOOLS)
                
                # 결과 포맷 처리: Function Calling인 경우와 일반 텍스트 구분
                if isinstance(chat_res, dict) and chat_res.get("type") == "function_call":
                    func_data = chat_res.get("function_call", {})
                    fn_name = func_data.get("name", "")
                    fn_args = func_data.get("args", {})
                    
                    log_activity(
                        user["username"],
                        "AI 챗봇 도구호출",
                        f"함수: {fn_name}",
                        is_api=True,
                        extra={"question": user_msg, "function_call": func_data}
                    )
                    self.send_json({
                        "type": "function_call",
                        "function_call": {
                            "name": fn_name,
                            "args": fn_args
                        },
                        "today_usage": used_count,
                        "daily_limit": limit
                    })
                    return

                # 일반 대화 텍스트인 경우
                reply = chat_res.get("text", "") if isinstance(chat_res, dict) else str(chat_res)
                
                # DB user_chat_logs에 챗봇 대화 저장
                chat_id = str(uuid.uuid4())[:8]
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                try:
                    supabase_request("user_chat_logs", "POST", body={
                        "username": user["username"],
                        "id": chat_id,
                        "question": user_msg,
                        "reply": reply,
                        "timestamp": now_str
                    })
                except Exception as log_err:
                    print(f"[chat log save error] {log_err}")

                log_activity(
                    user["username"],
                    "AI 챗봇 대화",
                    f"Q: {user_msg}",
                    is_api=True,
                    extra={"question": user_msg, "reply": reply}
                )
                self.send_json({
                    "type": "text",
                    "reply": reply,
                    "today_usage": used_count,
                    "daily_limit": limit
                })
            except Exception as e:
                self.send_json_error(500, f"API 오류: {str(e)}")

        # 2) AI 실무 지식 카드 생성 (가입 유저만 + 하루 5회 제한)
        elif self.path == "/api/generate-card":
            if not user:
                self.send_json_error(401, "비회원은 AI 지식카드 생성을 이용할 수 없습니다. 로그인 후 이용해주세요.")
                return

            ok, err_msg, used_count, limit = check_and_increment_daily_usage(user["username"])
            if not ok:
                self.send_json_error(429, err_msg)
                return

            chosen = req_data.get("topic") or "서버 하드웨어 장애(DIMM/ECC 오류, 핫스왑)"
            prompt = f"""당신은 데이터센터(DCO) 수석 엔지니어입니다.
주제: [{chosen}]
AWS 및 데이터센터 인프라 현장에서 필수적인 실무 꿀팁 카드를 아래 JSON 포맷으로 한국어로 정확히 작성해주세요.
반드시 마크다운 코드블록 없이 순수 JSON만 출력하세요:
{{
  "badge": "AI 실무 심화",
  "badgeColor": "#0ea5e9",
  "icon": "⚡",
  "title": "{chosen} 실무 핵심 가이드",
  "desc": "데이터센터 현장에서 실제로 적용되는 엔지니어 실무 팁:",
  "items": [
    "<strong>항목1 제목:</strong> 실무 설명...",
    "<strong>항목2 제목:</strong> 실무 설명...",
    "<strong>항목3 제목:</strong> 실무 설명..."
  ]
}}"""
            try:
                card_json_str = generate_gemini(prompt)
                card_data = json.loads(card_json_str)
                card_title = card_data.get("title", chosen)
                
                # 유저 개인 저장소에 지식카드 추가
                card_id = str(uuid.uuid4())[:8]
                card_data["isAi"] = True
                card_data["id"] = card_id
                card_data["created_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                try:
                    supabase_request("user_knowledge_cards", "POST", body={
                        "username": user["username"],
                        "id": card_id,
                        "data": card_data
                    })
                except Exception as card_err:
                    print(f"[card save error] {card_err}")

                log_activity(
                    user["username"],
                    "AI 지식카드 생성",
                    f"생성 카드: [{card_title}] (주제: {chosen})",
                    is_api=True,
                    extra={"topic": chosen, "card": card_data}
                )
                card_data["today_usage"] = used_count
                card_data["daily_limit"] = limit
                self.send_json(card_data)
            except Exception as e:
                self.send_json_error(500, f"지식 카드 생성 오류: {str(e)}")

        # 3) AI 실무 퀴즈 생성 (가입 유저만 + 하루 5회 제한)
        elif self.path == "/api/generate-quiz":
            if not user:
                self.send_json_error(401, "비회원은 AI 퀴즈 생성을 이용할 수 없습니다. 로그인 후 이용해주세요.")
                return

            ok, err_msg, used_count, limit = check_and_increment_daily_usage(user["username"])
            if not ok:
                self.send_json_error(429, err_msg)
                return

            chosen_topic = req_data.get("topic") or "Linux 서버 명령어 및 트러블슈팅 (smartctl, journalctl, lsof, top)"
            prompt = f"""당신은 AWS DCO 채용 및 기술 면접관입니다.
주제: [{chosen_topic}]
실제 현장 엔지니어가 접할 수 있는 4지선다형 기술 퀴즈 1문제를 한국어로 만들어주세요.
반드시 마크다운 코드블록 없이 순수한 JSON 문자열만 출력하세요:
{{
  "subject": "AI 실전 퀴즈",
  "question": "구체적인 기술 상황 또는 장애 시나리오 문제...",
  "options": ["보기1", "보기2", "보기3", "보기4"],
  "answer": 0,
  "explanation": "이 보기가 정답인 구체적인 실무 근거 및 해설"
}}
※ answer는 0, 1, 2, 3 중 올바른 정답의 인덱스 숫자여야 합니다."""
            try:
                quiz_json_str = generate_gemini(prompt)
                quiz_data = json.loads(quiz_json_str)
                quiz_q = quiz_data.get("question", "")

                # 유저 개인 저장소에 퀴즈 추가
                quiz_id = str(uuid.uuid4())[:8]
                quiz_data["isAi"] = True
                quiz_data["id"] = quiz_id
                quiz_data["created_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                try:
                    supabase_request("user_quizzes", "POST", body={
                        "username": user["username"],
                        "id": quiz_id,
                        "data": quiz_data
                    })
                except Exception as quiz_err:
                    print(f"[quiz save error] {quiz_err}")

                log_activity(
                    user["username"],
                    "AI 실전퀴즈 생성",
                    f"생성 퀴즈: {quiz_q[:70]}... (주제: {chosen_topic})",
                    is_api=True,
                    extra={"topic": chosen_topic, "quiz": quiz_data}
                )
                quiz_data["today_usage"] = used_count
                quiz_data["daily_limit"] = limit
                self.send_json(quiz_data)
            except Exception as e:
                self.send_json_error(500, f"퀴즈 출제 오류: {str(e)}")

        # 4) AI 학습실: 메모 기반 퀴즈 생성 (생성만 수행하고 DB에는 자동 저장하지 않음)
        elif self.path == "/api/study/generate-quiz":
            if not user:
                self.send_json_error(401, "비회원은 메모 기반 퀴즈 생성을 이용할 수 없습니다. 로그인 후 이용해주세요.")
                return

            ok, err_msg, used_count, limit = check_and_increment_daily_usage(user["username"])
            if not ok:
                self.send_json_error(429, err_msg)
                return

            req_subject = (req_data.get("subject") or "ALL").strip()
            req_count = max(1, min(3, int(req_data.get("count") or 1)))

            try:
                # 1. 서버가 인증된 사용자의 user_memos를 Supabase에서 직접 격리 조회
                memo_params = {"username": f"eq.{user['username']}", "select": "id,text,date,subject"}
                user_memos = supabase_request("user_memos", "GET", memo_params) or []

                # 과목 필터링 (ALL이 아닌 경우)
                if req_subject != "ALL" and req_subject != "전체":
                    s_lower = req_subject.lower()
                    filtered_memos = [
                        m for m in user_memos
                        if s_lower in (m.get("subject") or "").lower() or (m.get("subject") or "").lower() in s_lower
                    ]
                else:
                    filtered_memos = user_memos

                if not filtered_memos:
                    # 일일 호출 횟수 복구 (메모가 없어 생성을 진행하지 못한 경우 카운트 롤백)
                    try:
                        today = get_today_str()
                        supabase_request("api_daily_usage", "POST", body={
                            "username": user["username"],
                            "usage_date": today,
                            "call_count": max(0, used_count - 1),
                            "last_called_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                        }, headers_extra={"Prefer": "resolution=merge-duplicates,return=representation"})
                    except Exception:
                        pass

                    subject_desc = f"'{req_subject}' 과목의 " if req_subject not in ["ALL", "전체"] else ""
                    self.send_json_error(400, f"작성된 {subject_desc}학습 메모가 없습니다. 먼저 [메모/리마인더] 탭에서 학습 메모를 작성해 주세요.")
                    return

                # 유의미한 최근 메모 최대 8건 결합 (너무 긴 토큰 방지)
                recent_memos = filtered_memos[-8:]
                memo_context_lines = []
                for idx, m in enumerate(recent_memos, 1):
                    sub = m.get("subject", "학습")
                    txt = m.get("text", "").strip()
                    if txt:
                        memo_context_lines.append(f"[메모 {idx} / 과목: {sub}]\n{txt}")
                
                memo_context = "\n\n".join(memo_context_lines)

                prompt = f"""당신은 AWS DCO 수석 기술 면접관이자 전문 교육 강사입니다.
아래 제공된 [학습자 메모 내용]을 철저히 분석하여, 학습자가 필기한 핵심 기술 개념이나 문제 해결 과정을 평가할 수 있는 실무 4지선다형 기술 퀴즈를 정확히 {req_count}문제 출제해주세요.

[학습자 메모 내용]:
---
{memo_context}
---

[출제 요구사항]:
1. 반드시 학습자가 메모한 내용에 기반하여 정답과 오답을 도출해야 합니다.
2. 실무 현장 장애 해결(Troubleshooting) 시나리오 형태를 권장합니다.
3. 보기(options) 4개는 명확해야 하며 정답은 정확히 1개여야 합니다.
4. answer는 0, 1, 2, 3 중 올바른 정답의 인덱스 숫자여야 합니다.
5. 반드시 마크다운 코드블록(```json) 없이 순수한 JSON 배열 문자열만 출력하세요:
[
  {{
    "subject": "{req_subject if req_subject not in ['ALL', '전체'] else '실무 트레이닝'} (메모 기반)",
    "question": "구체적인 기술 상황 또는 장애 시나리오 문제...",
    "options": ["보기1", "보기2", "보기3", "보기4"],
    "answer": 0,
    "explanation": "이 보기가 정답인 구체적인 실무 근거 및 관련 메모 요약"
  }}
]"""

                quiz_json_str = generate_gemini(prompt)
                quizzes_raw = json.loads(quiz_json_str)

                # 단일 객체로 반환된 경우 배열로 감싸기
                if isinstance(quizzes_raw, dict):
                    quizzes_raw = [quizzes_raw]

                quizzes_list = []
                for q_item in quizzes_raw:
                    q_id = "memo_q_" + str(uuid.uuid4())[:8]
                    q_item["id"] = q_id
                    q_item["isAi"] = True
                    q_item["source"] = "MEMO_AI"
                    q_item["created_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    quizzes_list.append(q_item)

                # 요약 문자열 (첫 번째 문제 제목 표시)
                first_q = quizzes_list[0].get("question", "") if quizzes_list else ""
                log_details = f"메모 퀴즈 {len(quizzes_list)}문제 출제 (과목: {req_subject}): {first_q[:50]}..."

                log_activity(
                    user["username"],
                    "AI 메모 기반 퀴즈 생성",
                    log_details,
                    is_api=True,
                    extra={"subject": req_subject, "count": len(quizzes_list), "quizzes": quizzes_list}
                )

                # ⚠️ 중요: Supabase에 자동 저장하지 않고 생성된 퀴즈 배열만 반환
                self.send_json({
                    "success": True,
                    "quizzes": quizzes_list,
                    "today_usage": used_count,
                    "daily_limit": limit
                })
            except Exception as e:
                self.send_json_error(500, f"메모 퀴즈 생성 오류: {str(e)}")
        else:
            super().do_POST()

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def send_json_error(self, status, msg):
        self.send_json({"error": msg}, status=status)

def run(port=None):
    if port is None:
        port = int(os.getenv("PORT", 8080))
    ok, err = check_supabase_config()
    if not ok:
        print(f"⚠️  [Supabase 설정 경고] {err}")
    else:
        print("✅ Supabase 설정 확인 완료 (PostgreSQL 연동 준비)")

    server_address = ("", port)
    httpd = HTTPServer(server_address, DCODashboardHandler)
    print(f"🚀 DCO 대시보드 & AI 서버 실행 중 (포트: {port})")
    httpd.serve_forever()

if __name__ == "__main__":
    run()
