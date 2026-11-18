import os
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from dotenv import load_dotenv

# 상위 폴더 및 my-gemini-chat 또는 현재 폴더의 .env 탐색
env_paths = [
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / "my-gemini-chat" / ".env",
    Path(__file__).parent.parent.parent / "ask-once" / ".env",
]

loaded = False
for p in env_paths:
    if p.exists():
        load_dotenv(p)
        loaded = True
        break

if not loaded:
    load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
model_name = os.getenv("GEMINI_MODEL") or "gemini-3.5-flash-lite"

try:
    from google import genai
    from google.genai import types
    has_sdk = True
except ImportError:
    has_sdk = False

SYSTEM_INSTRUCTION = """
당신은 데이터센터 인프라 및 서버 룸 운영을 총괄하는 숙련된 시니어 DCO(Data Center Operations) 엔지니어 어시스턴트입니다.
사용자는 AWS DCO 양성과정 수강생 또는 데이터센터 초보 엔지니어입니다.
랙/서버 설치(Rack & Stack), 케이블링(UTP/광케이블), 쿨링 및 공조, 전력(PDU/UPS), 하드웨어 장애 대응 등에 대해
전문적이고 친절하며 안전 규정을 최우선으로 하는 간결하고 명확한 조언을 제공하세요.
"""

class DCODashboardHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # CORS 허용
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/chat":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            
            try:
                data = json.loads(body)
                user_msg = data.get("message", "").strip()
            except Exception:
                user_msg = ""

            if not user_msg:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "질문 내용을 입력해 주세요."}).encode("utf-8"))
                return

            if not api_key:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": "GEMINI_API_KEY가 설정되지 않았습니다. .env 파일에 키를 설정해 주세요."
                }).encode("utf-8"))
                return

            try:
                client = genai.Client(api_key=api_key)
                
                # 신규 키 지원 모델 우선 순위
                candidate_models = [model_name, "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"]
                reply_text = None
                last_err = None

                for target_model in candidate_models:
                    if not target_model:
                        continue
                    try:
                        response = client.models.generate_content(
                            model=target_model,
                            contents=user_msg,
                            config=types.GenerateContentConfig(
                                system_instruction=SYSTEM_INSTRUCTION,
                                temperature=0.7,
                            )
                        )
                        reply_text = response.text
                        break
                    except Exception as err:
                        last_err = err
                        continue

                if reply_text is None:
                    raise last_err or Exception("모든 지원 모델 응답 실패")

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"reply": reply_text}).encode("utf-8"))

            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"API 오류: {str(e)}"}).encode("utf-8"))
        else:
            super().do_POST()

def run(port=8080):
    server_address = ("", port)
    httpd = HTTPServer(server_address, DCODashboardHandler)
    print(f"🚀 DCO 대시보드 & AI 챗봇 서버 실행 중: http://localhost:{port}")
    httpd.serve_forever()

if __name__ == "__main__":
    run(8080)
