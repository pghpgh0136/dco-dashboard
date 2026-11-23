import os
import json
import uuid
import datetime
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "auth_data.json"

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

def load_data():
    if not DATA_FILE.exists():
        default_data = {
            "users": {
                "admin": {
                    "username": "admin",
                    "password": "admin123",
                    "name": "관리자",
                    "role": "admin",
                    "api_usage": 0,
                    "daily_usage": {get_today_str(): 0},
                    "created_at": "2026-11-20 09:00:00"
                },
                "user1": {
                    "username": "user1",
                    "password": "1234",
                    "name": "홍길동 엔지니어",
                    "role": "user",
                    "api_usage": 0,
                    "daily_usage": {get_today_str(): 0},
                    "created_at": "2026-11-20 09:00:00"
                }
            },
            "sessions": {},
            "user_data": {},  # username: {"memos": [], "cards": [], "quizzes": [], "chat": []}
            "logs": []
        }
        save_data(default_data)
        return default_data
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            if "user_data" not in d:
                d["user_data"] = {}
            return d
    except Exception:
        return {"users": {}, "sessions": {}, "user_data": {}, "logs": []}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def check_and_increment_daily_usage(username):
    data = load_data()
    user = data.get("users", {}).get(username)
    if not user:
        return False, "인증되지 않은 사용자입니다. 로그인 후 이용해주세요.", 0, 5

    # 관리자는 제한 없음
    if user.get("role") == "admin":
        today = get_today_str()
        daily = user.setdefault("daily_usage", {})
        daily[today] = daily.get(today, 0) + 1
        user["api_usage"] = user.get("api_usage", 0) + 1
        save_data(data)
        return True, "", daily[today], 9999

    today = get_today_str()
    daily = user.setdefault("daily_usage", {})
    current_today_count = daily.get(today, 0)

    if current_today_count >= 5:
        return False, f"오늘 API 일일 호출 한도(5회)를 모두 소진하셨습니다. (내일 0시에 초기화됩니다)", current_today_count, 5

    daily[today] = current_today_count + 1
    user["api_usage"] = user.get("api_usage", 0) + 1
    save_data(data)
    return True, "", daily[today], 5

def log_activity(username, action, details="", is_api=False, extra=None):
    data = load_data()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    log_entry = {
        "id": str(uuid.uuid4())[:8],
        "username": username or "익명",
        "name": data["users"].get(username, {}).get("name", "익명/게스트"),
        "role": data["users"].get(username, {}).get("role", "guest"),
        "action": action,
        "details": details,
        "is_api": is_api,
        "extra": extra,
        "timestamp": now_str
    }
    data["logs"].insert(0, log_entry)
    if len(data["logs"]) > 1000:
        data["logs"] = data["logs"][:1000]
        
    save_data(data)

def get_current_user(token):
    if not token:
        return None
    data = load_data()
    username = data.get("sessions", {}).get(token)
    if username and username in data.get("users", {}):
        return data["users"][username]
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
            
            data = load_data()
            today = get_today_str()
            users_list = []
            for u in data["users"].values():
                today_used = u.get("daily_usage", {}).get(today, 0)
                users_list.append({
                    "username": u["username"],
                    "name": u["name"],
                    "role": u["role"],
                    "api_usage": u.get("api_usage", 0),
                    "today_usage": today_used,
                    "created_at": u.get("created_at", "-")
                })
            
            self.send_json({
                "users": users_list,
                "logs": data.get("logs", [])[:200],
                "all_user_data": data.get("user_data", {})  # 관리자는 전체 유저 저장 데이터 열람 가능
            })
            return
            
        # 2. 내 정보 조회 (일일 남은 횟수 포함)
        elif self.path == "/api/auth/me":
            token = self.get_token_from_header()
            user = get_current_user(token)
            if not user:
                self.send_json_error(401, "인증되지 않은 사용자입니다.")
                return
            today = get_today_str()
            today_used = user.get("daily_usage", {}).get(today, 0)
            max_limit = 9999 if user.get("role") == "admin" else 5
            self.send_json({
                "username": user["username"],
                "name": user["name"],
                "role": user["role"],
                "api_usage": user.get("api_usage", 0),
                "today_usage": today_used,
                "daily_limit": max_limit
            })
            return

        # 3. 로그인한 유저의 개인 저장 데이터 조회 (메모, 생성된 지식카드, 생성된 퀴즈, 챗봇 기록)
        elif self.path == "/api/user/data":
            token = self.get_token_from_header()
            user = get_current_user(token)
            if not user:
                self.send_json_error(401, "로그인이 필요한 서비스입니다.")
                return
            
            data = load_data()
            u_data = data.get("user_data", {}).get(user["username"], {
                "memos": [],
                "cards": [],
                "quizzes": [],
                "chat": []
            })
            self.send_json(u_data)
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
            data = load_data()
            if u_name in data["users"] and data["users"][u_name]["password"] == u_pass:
                user_info = data["users"][u_name]
                new_token = str(uuid.uuid4())
                data["sessions"][new_token] = u_name
                save_data(data)
                
                today = get_today_str()
                today_used = user_info.get("daily_usage", {}).get(today, 0)
                max_limit = 9999 if user_info.get("role") == "admin" else 5

                log_activity(u_name, "로그인", f"로그인 성공 (IP: {self.client_address[0]})", is_api=False)
                self.send_json({
                    "token": new_token,
                    "user": {
                        "username": user_info["username"],
                        "name": user_info["name"],
                        "role": user_info["role"],
                        "api_usage": user_info.get("api_usage", 0),
                        "today_usage": today_used,
                        "daily_limit": max_limit
                    }
                })
            else:
                self.send_json_error(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
            return

        # 0-2) 로그아웃
        elif self.path == "/api/auth/logout":
            if token:
                data = load_data()
                if token in data["sessions"]:
                    un = data["sessions"].pop(token)
                    save_data(data)
                    log_activity(un, "로그아웃", "로그아웃 완료", is_api=False)
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
            data = load_data()
            if u_name in data["users"]:
                self.send_json_error(400, "이미 존재하는 아이디입니다.")
                return
            
            today = get_today_str()
            data["users"][u_name] = {
                "username": u_name,
                "password": u_pass,
                "name": u_display,
                "role": "user",
                "api_usage": 0,
                "daily_usage": {today: 0},
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            # 개인 데이터 저장소 초기화
            if "user_data" not in data:
                data["user_data"] = {}
            data["user_data"][u_name] = {
                "memos": [],
                "cards": [],
                "quizzes": [],
                "chat": []
            }
            new_token = str(uuid.uuid4())
            data["sessions"][new_token] = u_name
            save_data(data)
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
            return

        # 0-4) 유저 개인 데이터 동기화 (메모 저장/삭제 등)
        elif self.path == "/api/user/save-data":
            if not user:
                self.send_json_error(401, "로그인이 필요한 서비스입니다.")
                return
            data_type = req_data.get("type")  # memos, cards, quizzes, chat
            items = req_data.get("items")
            if data_type in ["memos", "cards", "quizzes", "chat"] and items is not None:
                data = load_data()
                u_data = data.setdefault("user_data", {}).setdefault(user["username"], {
                    "memos": [], "cards": [], "quizzes": [], "chat": []
                })
                u_data[data_type] = items
                save_data(data)
                self.send_json({"success": True})
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
                
                # 유저 개인 저장소에 챗봇 대화 추가
                data = load_data()
                u_chat = data.setdefault("user_data", {}).setdefault(user["username"], {}).setdefault("chat", [])
                chat_entry = {
                    "id": str(uuid.uuid4())[:8],
                    "question": user_msg,
                    "reply": reply,
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                u_chat.append(chat_entry)
                save_data(data)

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
                data = load_data()
                u_cards = data.setdefault("user_data", {}).setdefault(user["username"], {}).setdefault("cards", [])
                card_data["isAi"] = True
                card_data["id"] = str(uuid.uuid4())[:8]
                card_data["created_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                u_cards.append(card_data)
                save_data(data)

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
                data = load_data()
                u_quizzes = data.setdefault("user_data", {}).setdefault(user["username"], {}).setdefault("quizzes", [])
                quiz_data["isAi"] = True
                quiz_data["id"] = str(uuid.uuid4())[:8]
                quiz_data["created_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                u_quizzes.append(quiz_data)
                save_data(data)

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
    load_data()
    server_address = ("", port)
    httpd = HTTPServer(server_address, DCODashboardHandler)
    print(f"🚀 DCO 대시보드 & AI 서버 실행 중 (포트: {port})")
    httpd.serve_forever()

if __name__ == "__main__":
    run()
