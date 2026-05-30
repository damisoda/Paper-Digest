"""arXiv PDF 다운로드 및 섹션별 텍스트 추출 모듈

전략:
- arXiv PDF를 .pdf_cache/ 에 캐싱 (재실행 시 재다운로드 없음)
- PyMuPDF로 텍스트 블록 추출 → 섹션 헤더 감지
- Introduction / Method / Experiments / Results 섹션 우선 선택
- 최대 4000자로 잘라 프롬프트 길이 조절
"""
import re
import requests
import fitz  # PyMuPDF
from pathlib import Path
from loguru import logger

from config import config


# 섹션 우선순위 — 숫자가 작을수록 먼저 예산을 배정 (요약 4개 항목에 직접 기여하는 순서)
# 1순위: 방법/결과 (핵심 방법·주요 결과 항목의 근거)
# 2순위: 도입/결론 (한 줄 요약·왜 중요한가의 근거)
# 3순위: 배경/관련연구 (보조)
_TIER1 = ["method", "methodology", "approach", "model", "framework", "architecture", "proposed",
          "experiment", "evaluation", "result", "ablation", "analysis", "finding"]
_TIER2 = ["introduction", "conclusion", "discussion", "summary"]
_TIER3 = ["background", "related"]
_USEFUL = _TIER1 + _TIER2 + _TIER3

# 건너뛸 섹션 키워드
_SKIP = ["reference", "bibliography", "acknowledgment", "appendix", "funding"]


def _section_priority(name: str) -> int | None:
    """섹션명 → 우선순위(1~3). 유용하지 않으면 None."""
    lower = name.lower()
    if any(kw in lower for kw in _TIER1):
        return 1
    if any(kw in lower for kw in _TIER2):
        return 2
    if any(kw in lower for kw in _TIER3):
        return 3
    return None


class PDFExtractor:
    def __init__(self, cache_dir: str = ".pdf_cache", max_pages: int = 15,
                 max_section_chars: int = None, max_total_chars: int = None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.max_pages = max_pages
        self.max_section_chars = max_section_chars or config.PDF_MAX_SECTION_CHARS
        self.max_total_chars = max_total_chars or config.PDF_MAX_TOTAL_CHARS

    # ── 다운로드 ────────────────────────────────────────────────────

    def _pdf_path(self, arxiv_id: str) -> Path:
        return self.cache_dir / f"{arxiv_id}.pdf"

    def _download(self, arxiv_id: str) -> Path | None:
        """arXiv PDF 다운로드 (캐시 있으면 스킵)"""
        pdf_path = self._pdf_path(arxiv_id)
        if pdf_path.exists():
            logger.debug(f"[PDF] 캐시 사용: {arxiv_id}")
            return pdf_path

        url = f"https://arxiv.org/pdf/{arxiv_id}"
        try:
            resp = requests.get(
                url, timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (compatible; PaperDigest/1.0)"},
                allow_redirects=True,
            )
            resp.raise_for_status()
            if b"%PDF" not in resp.content[:10]:
                logger.warning(f"[PDF] 유효하지 않은 PDF 응답: {arxiv_id}")
                return None
            pdf_path.write_bytes(resp.content)
            logger.info(f"[PDF] 다운로드 완료: {arxiv_id} ({len(resp.content)//1024}KB)")
            return pdf_path
        except requests.exceptions.Timeout:
            logger.warning(f"[PDF] 타임아웃: {arxiv_id}")
        except requests.exceptions.HTTPError as e:
            logger.warning(f"[PDF] HTTP 오류 ({arxiv_id}): {e}")
        except Exception as e:
            logger.warning(f"[PDF] 다운로드 실패 ({arxiv_id}): {e}")
        return None

    def prefetch(self, arxiv_id: str) -> bool:
        """PDF를 캐시에 미리 받아둔다 (성공 여부 반환). 스레드풀에서 호출 안전.

        서로 다른 arxiv_id는 서로 다른 파일 경로에 기록되므로 동시 실행해도 충돌이 없다.
        """
        return self._download(arxiv_id) is not None

    # ── 섹션 추출 ───────────────────────────────────────────────────

    def _is_section_header(self, text: str) -> bool:
        """텍스트가 섹션 헤더인지 판단"""
        if not text or len(text) > 80:
            return False
        lower = text.lower().strip()
        # "1. Introduction", "2 Method", "Related Work" 등 패턴
        has_keyword = any(kw in lower for kw in _USEFUL + _SKIP)
        looks_like_header = bool(re.match(r'^(\d+\.?\s+)?[A-Z]', text.strip()))
        return has_keyword and looks_like_header

    def _extract_sections(self, pdf_path: Path) -> list[tuple[str, str]]:
        """[(섹션명, 텍스트), ...] 형태로 반환"""
        try:
            doc = fitz.open(str(pdf_path))
        except Exception as e:
            logger.warning(f"[PDF] 파일 열기 실패: {e}")
            return []

        sections: list[tuple[str, str]] = []
        current_name = "header"
        current_lines: list[str] = []

        pages = min(len(doc), self.max_pages)
        for page_num in range(pages):
            page = doc[page_num]
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    text = " ".join(
                        s["text"] for s in line.get("spans", [])
                    ).strip()
                    if not text:
                        continue

                    if self._is_section_header(text):
                        # 이전 섹션 저장
                        if current_lines:
                            sections.append((current_name, " ".join(current_lines)))
                        current_name = text.strip()
                        current_lines = []
                    else:
                        current_lines.append(text)

        if current_lines:
            sections.append((current_name, " ".join(current_lines)))

        doc.close()
        return sections

    # ── 공개 인터페이스 ─────────────────────────────────────────────

    def _fallback_page_text(self, pdf_path: Path) -> str:
        """섹션 감지 실패 시 페이지별 텍스트 추출 fallback"""
        try:
            doc = fitz.open(str(pdf_path))
            pages = min(len(doc), self.max_pages)
            parts, total = [], 0
            for i in range(pages):
                text = doc[i].get_text("text").strip()
                if not text:
                    continue
                chunk = f"[PAGE {i+1}]\n{text[:1600]}"
                parts.append(chunk)
                total += len(chunk)
                if total >= self.max_total_chars:
                    break
            doc.close()
            logger.info(f"[PDF] 페이지 fallback 완료: {len(parts)}페이지")
            return "\n\n".join(parts)
        except Exception as e:
            logger.warning(f"[PDF] fallback 추출 실패: {e}")
            return ""

    def get_grounding_text(self, arxiv_id: str) -> str:
        """수치 grounding 검증 전용 — 캐시된 PDF의 본문 텍스트를 넓게 추출.

        프롬프트에 넣는 텍스트(섹션 선별·14K 제한)와 달리, 잘림으로 인한 오탐을
        줄이려 가능한 많은 페이지 텍스트를 그대로 모은다. LLM에는 전달하지 않는다.
        """
        pdf_path = self._pdf_path(arxiv_id)
        if not pdf_path.exists():
            return ""
        try:
            doc = fitz.open(str(pdf_path))
            parts = [doc[i].get_text("text") for i in range(min(len(doc), self.max_pages))]
            doc.close()
            return " ".join(parts)
        except Exception as e:
            logger.debug(f"[PDF] grounding 텍스트 추출 실패 ({arxiv_id}): {e}")
            return ""

    def get_paper_text(self, arxiv_id: str) -> str:
        """
        논문의 핵심 섹션 텍스트를 하나의 문자열로 반환.
        섹션 감지 실패 시 페이지별 텍스트로 자동 fallback.
        실패 시 빈 문자열 반환 (초록 fallback은 호출자가 처리).
        """
        pdf_path = self._download(arxiv_id)
        if not pdf_path:
            return ""

        sections = self._extract_sections(pdf_path)

        # 유용한 섹션 후보 추출 (SKIP 제외, 우선순위 부여 + 문서 순서 보존)
        candidates: list[tuple[int, int, str, str]] = []  # (priority, order, name, text)
        for order, (name, text) in enumerate(sections):
            lower_name = name.lower()
            if any(sk in lower_name for sk in _SKIP):
                continue
            prio = _section_priority(name)
            if prio is None:
                continue
            candidates.append((prio, order, name, text))

        # 유용한 섹션이 2개 미만이면 페이지 단위 fallback
        if len(candidates) < 2:
            logger.info(f"[PDF] 섹션 감지 부족 ({len(candidates)}개) → 페이지 fallback: {arxiv_id}")
            return self._fallback_page_text(pdf_path)

        # 우선순위(방법·결과 먼저) → 문서 순서로 예산 배정
        candidates.sort(key=lambda c: (c[0], c[1]))
        selected: list[tuple[int, str, str]] = []  # (order, name, chunk)
        total = 0
        for prio, order, name, text in candidates:
            chunk = f"[{name.upper()}]\n{text[:self.max_section_chars]}"
            if total + len(chunk) > self.max_total_chars:
                continue  # 예산 초과 섹션은 건너뛰되 더 짧은 후속 섹션은 계속 시도
            selected.append((order, name, chunk))
            total += len(chunk)

        # 최종 출력은 다시 문서 순서로 정렬 → LLM이 논리 흐름을 따라가기 쉽게
        selected.sort(key=lambda s: s[0])
        parts = [chunk for _, _, chunk in selected]

        result = "\n\n".join(parts)
        logger.info(f"[PDF] 섹션 텍스트 준비: {arxiv_id} ({total}자, {len(parts)}섹션)")
        return result
