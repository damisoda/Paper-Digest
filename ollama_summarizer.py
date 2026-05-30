"""Ollama (gemma4:e4b)로 논문을 한국어 요약하는 모듈

구조화 출력(Structured Output) 방식:
  Ollama `format` 파라미터에 JSON 스키마를 넘겨 모델이 항상
  {one_line, method, importance, results} 4개 키의 JSON만 생성하도록 강제한다.
  → 정규식 파싱·파싱 실패 경로가 사라지고, 결과가 결정론적으로 안정된다.
"""
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, Future
from loguru import logger

from config import config
from database import Paper
from pdf_extractor import PDFExtractor


# ── 구조화 출력 스키마 ───────────────────────────────────────────────
# Ollama가 이 스키마에 맞는 JSON만 생성하도록 강제 (constrained decoding)
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "one_line":   {"type": "string", "minLength": 10},
        "method":     {"type": "string", "minLength": 30},
        "importance": {"type": "string", "minLength": 30},
        "results":    {"type": "string", "minLength": 20},
    },
    "required": ["one_line", "method", "importance", "results"],
}

_FIELD_KEYS = ("one_line", "method", "importance", "results")


_PROMPT_WITH_PDF = """\
당신은 AI/ML 논문을 한국어로 깊이 있게 요약하는 시니어 연구자입니다.
아래 논문 정보와 본문(섹션별)을 읽고, 4개 항목을 JSON으로 작성하세요.

=== 논문 정보 ===
제목: {title}
저자: {authors}
카테고리: {category}
초록:
{abstract}

=== 논문 본문 (섹션별, 우선순위 순) ===
{paper_text}
=================

각 항목 작성 지침:
- one_line: 이 논문이 무엇을 하는지 핵심을 한 문장으로. (1~2문장)
- method: 제안하는 기술·알고리즘·아키텍처를 동작 원리 수준까지 구체적으로. 기존 방법 대비 핵심 차별점을 반드시 포함. (3~5문장)
- importance: 어떤 문제를 해결하며 AI/ML 분야에서 갖는 의미와 실용적 가치. (2~4문장)
- results: 보고된 정량적 성능을 수치와 함께. 벤치마크/데이터셋 이름, 비교 대상, 개선폭(%, 점수 등)을 명시. (2~4문장)

엄격한 규칙:
- 반드시 한국어로 작성. 고유명사·약어·벤치마크명은 원문 유지 가능.
- 본문에 근거한 구체적 서술만. 추상적 미사여구·일반론 금지.
- 본문에 해당 정보가 없으면 지어내지 말고 "본문에 명시되지 않음"이라고 쓸 것.
- 출력은 지정된 JSON 스키마만. 그 외 텍스트·마크다운·코드펜스 금지.\
"""

_PROMPT_ABSTRACT_ONLY = """\
당신은 AI/ML 논문을 한국어로 깊이 있게 요약하는 시니어 연구자입니다.
아래 논문 정보(초록 기준)를 읽고, 4개 항목을 JSON으로 작성하세요.

=== 논문 정보 ===
제목: {title}
저자: {authors}
카테고리: {category}
초록:
{abstract}
=================

각 항목 작성 지침:
- one_line: 이 논문이 무엇을 하는지 핵심을 한 문장으로. (1~2문장)
- method: 제안하는 기술·알고리즘·아키텍처를 가능한 구체적으로. 기존 방법 대비 차별점 포함. (2~4문장)
- importance: 어떤 문제를 해결하며 갖는 의미와 실용적 가치. (2~3문장)
- results: 초록에 언급된 정량적 성능·핵심 발견을 수치와 함께. (1~3문장)

엄격한 규칙:
- 반드시 한국어로 작성. 고유명사·약어·벤치마크명은 원문 유지 가능.
- 초록에 근거한 구체적 서술만. 추상적 미사여구 금지.
- 초록에 정보가 없으면 지어내지 말고 "초록에 명시되지 않음"이라고 쓸 것.
- 출력은 지정된 JSON 스키마만. 그 외 텍스트·마크다운·코드펜스 금지.\
"""


class OllamaSummarizer:
    def __init__(self, base_url: str = None, model: str = None, timeout: int = None,
                 max_retries: int = None):
        self.base_url = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or config.OLLAMA_MODEL
        self.timeout = timeout or config.OLLAMA_TIMEOUT
        self.max_retries = config.OLLAMA_MAX_RETRIES if max_retries is None else max_retries
        self._url = f"{self.base_url}/api/generate"
        self._pdf = PDFExtractor(
            cache_dir=config.PDF_CACHE_DIR,
            max_pages=config.PDF_MAX_PAGES,
        )

    def _call(self, prompt: str) -> str:
        """Ollama /api/generate 호출 (구조화 출력) → JSON 문자열 반환"""
        try:
            resp = requests.post(
                self._url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": SUMMARY_SCHEMA,  # ← JSON 스키마로 출력 강제
                    "options": {
                        "temperature": 0.2,
                        "num_ctx": config.OLLAMA_NUM_CTX,
                        "num_predict": config.OLLAMA_NUM_PREDICT,
                    },
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

    @staticmethod
    def _parse(raw: str) -> dict | None:
        """구조화 JSON 응답 파싱 + 검증. 실패 시 None."""
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # 혹시 코드펜스/잡텍스트가 섞이면 첫 { ~ 마지막 } 만 추려 재시도
            start, end = raw.find("{"), raw.rfind("}")
            if start == -1 or end <= start:
                return None
            try:
                data = json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                return None
        if not isinstance(data, dict):
            return None
        parsed = {k: str(data.get(k, "")).strip() for k in _FIELD_KEYS}
        # 핵심 항목이 비어 있으면 무효 처리 (재시도 유도)
        if not parsed["one_line"] or not parsed["method"]:
            return None
        return parsed

    def _build_prompt(self, paper: Paper) -> str:
        """PDF 본문이 있으면 본문 프롬프트, 없으면 초록 전용 프롬프트"""
        paper_text = self._pdf.get_paper_text(paper.arxiv_id)
        if paper_text:
            logger.info(f"[Ollama] PDF 본문 사용: {paper.arxiv_id} ({len(paper_text)}자)")
            return _PROMPT_WITH_PDF.format(
                title=paper.title, authors=paper.authors,
                category=paper.categories, abstract=paper.abstract,
                paper_text=paper_text,
            )
        logger.info(f"[Ollama] 초록 전용 모드: {paper.arxiv_id}")
        return _PROMPT_ABSTRACT_ONLY.format(
            title=paper.title, authors=paper.authors,
            category=paper.categories, abstract=paper.abstract,
        )

    def summarize(self, paper: Paper) -> Paper:
        """논문 한 편 요약 후 Paper 필드에 결과 채워 반환 (실패 시 재시도)"""
        logger.info(f"[Ollama] 요약: {paper.arxiv_id} | {paper.title[:50]}")
        prompt = self._build_prompt(paper)

        attempts = self.max_retries + 1
        last_err = "알 수 없는 오류"
        for attempt in range(1, attempts + 1):
            try:
                raw = self._call(prompt)
                parsed = self._parse(raw)
                if parsed is None:
                    last_err = "구조화 출력 파싱/검증 실패"
                    logger.warning(f"[Ollama] {last_err} (시도 {attempt}/{attempts}): {paper.arxiv_id}")
                    if attempt < attempts:
                        time.sleep(1.5)
                    continue
                paper.raw_summary = raw
                paper.summary_one_line = parsed["one_line"]
                paper.summary_method = parsed["method"]
                paper.summary_importance = parsed["importance"]
                paper.summary_results = parsed["results"]
                logger.success(f"[Ollama] 완료: {paper.arxiv_id}" + (f" (재시도 {attempt-1}회)" if attempt > 1 else ""))
                return paper
            except RuntimeError as e:
                last_err = str(e)
                logger.warning(f"[Ollama] 호출 실패 (시도 {attempt}/{attempts}, {paper.arxiv_id}): {e}")
                if attempt < attempts:
                    time.sleep(2.0)

        logger.error(f"[Ollama] 최종 실패 ({paper.arxiv_id}): {last_err}")
        paper.summary_one_line = f"요약 실패: {last_err}"
        return paper

    def summarize_batch(self, papers: list[Paper]) -> list[Paper]:
        """여러 논문 요약.

        LLM 호출(GPU)은 직렬을 유지하되, PDF 다운로드만 백그라운드 스레드풀로
        미리 받아둔다(prefetch) — GPU가 다음 논문 PDF의 네트워크 대기에 묶이지 않도록.
        """
        total = len(papers)
        workers = max(1, min(config.PDF_PREFETCH_WORKERS, total))
        logger.info(f"[Ollama] 배치 시작: {total}편 (PDF prefetch 워커 {workers})")

        results: list[Paper] = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pdf-prefetch") as pool:
            # 모든 논문 PDF 다운로드를 동시에 시작 (캐시에 적재)
            futures: dict[str, Future] = {
                p.arxiv_id: pool.submit(self._pdf.prefetch, p.arxiv_id) for p in papers
            }
            for i, paper in enumerate(papers, 1):
                logger.info(f"[Ollama] [{i}/{total}] {paper.arxiv_id}")
                # 이 논문 PDF 다운로드가 끝날 때까지만 대기 (나머지는 계속 병렬 진행)
                try:
                    futures[paper.arxiv_id].result(timeout=60)
                except Exception as e:
                    logger.debug(f"[Ollama] prefetch 대기 실패 ({paper.arxiv_id}): {e} — 초록 모드로 진행")
                # 요약 시점엔 PDF가 캐시에 있으므로 get_paper_text는 캐시 히트
                results.append(self.summarize(paper))

        ok = sum(1 for p in results if not p.summary_one_line.startswith("요약 실패"))
        logger.info(f"[Ollama] 배치 완료: {total}편 (성공 {ok} / 실패 {total - ok})")
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
