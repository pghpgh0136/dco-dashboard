import os
import json
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# 상위 폴더 및 my-gemini-chat 또는 현재 폴더의 .env 탐색
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
당신은 데이터센터 인프라 및 서버 룸 운영을 총괄하는 숙련된 시니어 DCO(Data Center Operations) 엔지니어 어시스턴트입니다.
사용자는 AWS DCO 양성과정 수강생 또는 데이터센터 초보 엔지니어입니다.
랙/서버 설치(Rack & Stack), 케이블링(UTP/광케이블), 쿨링 및 공조, 전력(PDU/UPS), 하드웨어 장애 대응 등에 대해
전문적이고 친절하며 안전 규정을 최우선으로 하는 간결하고 명확한 조언을 제공하세요.
"""

# 현재 실제 정상 작동하는 최신 Gemini 모델 우선순위
CANDIDATE_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.8-flash"
]

def generate_gemini(prompt_text, system_instruction=None):
    if not api_key:
        raise Exception(".env 파일에 GEMINI_API_KEY가 설정되지 않았습니다.")
    
    last_error = None
    # 503 또는 일시 장애 시 다음 모델로 즉시 자동 시도
    for model in CANDIDATE_MODELS:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt_text}]}],
                "generationConfig": {"temperature": 0.7}
            }
            if system_instruction:
                payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=25) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                raw = res_data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                return raw.replace("```json", "").replace("```", "").strip()
        except urllib.error.HTTPError as e:
            last_error = e
            # 503(Service Unavailable) 또는 404/429인 경우 다른 모델로 재시도
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}

        # 1) AI 챗봇
        if self.path == "/api/chat":
            user_msg = req_data.get("message", "").strip()
            if not user_msg:
                self.send_json_error(400, "질문 내용을 입력해 주세요.")
                return
            try:
                reply = generate_gemini(user_msg, SYSTEM_INSTRUCTION)
                self.send_json({"reply": reply})
            except Exception as e:
                self.send_json_error(500, f"API 오류: {str(e)}")

        # 2) AI 실무 지식 카드 생성
        elif self.path == "/api/generate-card":
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
                self.send_json(card_data)
            except Exception as e:
                self.send_json_error(500, f"지식 카드 생성 오류: {str(e)}")

        # 3) AI 실무 퀴즈 생성
        elif self.path == "/api/generate-quiz":
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

def run(port=8080):
    server_address = ("", port)
    httpd = HTTPServer(server_address, DCODashboardHandler)
    print(f"🚀 DCO 대시보드 & AI 서버 실행 중: http://localhost:{port}")
    httpd.serve_forever()

if __name__ == "__main__":
    run(8080)
