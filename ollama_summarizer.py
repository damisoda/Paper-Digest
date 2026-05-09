"""Ollama (gemma4:e4b)로 논문을 한국어 요약하는 모듈"""
import re
import requests
from loguru import logger

from config import config
from database import Paper


PROMPT_TEMPLATE = """\
당신은 AI/ML 논문을 한국어로 요약하는 전문가입니다.
아래 논문 정보를 읽고, 지정된 형식에 맞춰 정확하고 풍부하게 요약하세요.

=== 논문 정보 ===
제목: {title}
저자: {authors}
카테고리: {category}
초록:
{abstract}
=================

아래 4개 항목을 반드시 이모지와 함께 작성하세요.
각 항목은 최소 2문장 이상, 구체적인 내용을 포함해야 합니다.

📌 한 줄 요약: 이 논문이 무엇을 하는지 핵심을 한 문장으로 명확하게.
🔍 핵심 방법: 논문에서 제안하는 기술, 알고리즘, 아키텍처를 구체적으로 설명. 기존 방법과의 차이점 포함.
💡 왜 중요한가: 이 연구가 AI/ML 분야에서 갖는 의미와 실용적 가치. 어떤 문제를 해결하는가.
📊 주요 결과: 논문에서 보고한 정량적 성능(수치, 벤치마크), 또는 핵심 발견 사항.

규칙:
- 반드시 한국어로만 작성
- 각 항목 이모지(📌 🔍 💡 📊)는 반드시 포함
- 추상적인 표현 금지, 논문 내용에 근거한 구체적 서술
- 모르는 내용은 초록에서 추론하여 작성\
"""

# 요약 섹션 파싱용 정규식 — 우선순위 순으로 시도
_PATTERN_SETS = [
    # 1순위: 이모지 포함 (정상 응답)
    {
        "one_line":   r"📌\s*한 줄 요약\s*[:\-]?\s*(.+?)(?=🔍|💡|📊|$)",
        "method":     r"🔍\s*핵심 방법\s*[:\-]?\s*(.+?)(?=📌|💡|📊|$)",
        "importance": r"💡\s*왜 중요한가\s*[:\-]?\s*(.+?)(?=📌|🔍|📊|$)",
        "results":    r"📊\s*주요 결과\s*[:\-]?\s*(.+?)(?=📌|🔍|💡|$)",
    },
    # 2순위: 이모지 없는 한글 헤더
    {
        "one_line":   r"한 줄 요약\s*[:\-]?\s*(.+?)(?=핵심 방법|왜 중요|주요 결과|$)",
        "method":     r"핵심 방법\s*[:\-]?\s*(.+?)(?=한 줄 요약|왜 중요|주요 결과|$)",
        "importance": r"왜 중요한가?\s*[:\-]?\s*(.+?)(?=한 줄 요약|핵심 방법|주요 결과|$)",
        "results":    r"주요 결과\s*[:\-]?\s*(.+?)(?=한 줄 요약|핵심 방법|왜 중요|$)",
    },
    # 3순위: ** 마크다운 볼드 헤더
    {
        "one_line":   r"\*+[📌]?\s*한 줄 요약[:\*\s]*(.+?)(?=\*+[🔍📌💡📊]|\Z)",
        "method":     r"\*+[🔍]?\s*핵심 방법[:\*\s]*(.+?)(?=\*+[🔍📌💡📊]|\Z)",
        "importance": r"\*+[💡]?\s*왜 중요한가[:\*\s]*(.+?)(?=\*+[🔍📌💡📊]|\Z)",
        "results":    r"\*+[📊]?\s*주요 결과[:\*\s]*(.+?)(?=\*+[🔍📌💡📊]|\Z)",
    },
]


class OllamaSummarizer:
    def __init__(self, base_url: str = None, model: str = None, timeout: int = None):
        self.base_url = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or config.OLLAMA_MODEL
        self.timeout = timeout or config.OLLAMA_TIMEOUT
        self._url = f"{self.base_url}/api/generate"

    def _call(self, prompt: str) -> str:
        """Ollama /api/generate 호출 → 응답 텍스트 반환"""
        try:
            resp = requests.post(
                self._url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 2048},
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"Ollama 서버({self.base_url})에 연결할 수 없습니다.")
        except requests.exceptions.Timeout:
            raise RuntimeError(f"Ollama 응답 타임아웃 ({self.timeout}초).")
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"Ollama HTTP 오류: {e}")

    def _parse(self, raw: str) -> dict:
        """응답 텍스트에서 4개 섹션 파싱 — 패턴 셋을 순서대로 시도"""
        keys = ["one_line", "method", "importance", "results"]
        for pattern_set in _PATTERN_SETS:
            parsed = {k: "" for k in keys}
            for key, pattern in pattern_set.items():
                m = re.search(pattern, raw, re.DOTALL)
                if m:
                    parsed[key] = m.group(1).strip()
            # 하나라도 파싱 성공하면 해당 결과 반환
            if any(parsed.values()):
                return parsed

        # 모든 패턴 실패 시 원본 첫 500자를 한 줄 요약에 저장
        logger.warning("[Ollama] 요약 파싱 실패 — 원본을 저장합니다.")
        return {k: "" for k in keys} | {"one_line": raw[:500]}

    def summarize(self, paper: Paper) -> Paper:
        """논문 한 편 요약 후 Paper 필드에 결과 채워 반환"""
        logger.info(f"[Ollama] 요약: {paper.arxiv_id} | {paper.title[:50]}")
        prompt = PROMPT_TEMPLATE.format(
            title=paper.title,
            authors=paper.authors,
            category=paper.categories,
            abstract=paper.abstract,
        )
        try:
            raw = self._call(prompt)
            p = self._parse(raw)
            paper.raw_summary = raw
            paper.summary_one_line = p["one_line"]
            paper.summary_method = p["method"]
            paper.summary_importance = p["importance"]
            paper.summary_results = p["results"]
            logger.success(f"[Ollama] 완료: {paper.arxiv_id}")
        except RuntimeError as e:
            logger.error(f"[Ollama] 실패 ({paper.arxiv_id}): {e}")
            paper.summary_one_line = f"요약 실패: {e}"
        return paper

    def summarize_batch(self, papers: list[Paper]) -> list[Paper]:
        """여러 논문 순차 요약"""
        total = len(papers)
        logger.info(f"[Ollama] 배치 시작: {total}편")
        results = []
        for i, paper in enumerate(papers, 1):
            logger.info(f"[Ollama] [{i}/{total}] {paper.arxiv_id}")
            results.append(self.summarize(paper))
        logger.info(f"[Ollama] 배치 완료: {total}편")
        return results

    def health_check(self) -> bool:
        """서버 및 모델 가용 여부 확인"""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            base = self.model.split(":")[0]
            ok = any(base in m for m in models)
            if not ok:
                logger.warning(f"[Ollama] '{self.model}' 없음. 사용 가능: {models}")
            return ok
        except Exception as e:
            logger.error(f"[Ollama] 헬스체크 실패: {e}")
            return False
