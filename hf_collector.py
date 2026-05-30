"""HuggingFace Papers API로 트렌딩 논문을 수집하는 모듈

hf.co/papers 의 upvote 기반 트렌딩 논문을 가져옵니다.
카테고리는 arXiv API에서 직접 조회하여 정확하게 설정합니다.
"""
import arxiv
import requests
from datetime import datetime, timezone
from loguru import logger

from config import config
from database import Paper

HF_PAPERS_API = "https://huggingface.co/api/papers"


class HFCollector:
    def __init__(self, limit: int = None, min_upvotes: int = None):
        self.limit = limit or config.HF_TRENDING_LIMIT
        self.min_upvotes = min_upvotes or config.HF_MIN_UPVOTES
        self._arxiv = arxiv.Client(page_size=50, delay_seconds=1.0, num_retries=2)

    def _fetch_arxiv_categories(self, arxiv_ids: list[str]) -> dict[str, str]:
        """arXiv API로 실제 primary 카테고리 일괄 조회"""
        if not arxiv_ids:
            return {}
        logger.info(f"[HF] arXiv 카테고리 조회: {len(arxiv_ids)}편")
        cat_map: dict[str, str] = {}
        try:
            search = arxiv.Search(id_list=arxiv_ids, max_results=len(arxiv_ids))
            for result in self._arxiv.results(search):
                rid = result.entry_id.split("/")[-1].rsplit("v", 1)[0]
                # primary category는 categories 리스트의 첫 번째
                cat = result.categories[0] if result.categories else "cs.AI"
                cat_map[rid] = cat
        except Exception as e:
            logger.warning(f"[HF] arXiv 카테고리 조회 실패: {e}")
        return cat_map

    def _to_paper(self, item: dict, category: str) -> Paper | None:
        """HF API 응답 → Paper 변환"""
        arxiv_id = item.get("id", "").strip()
        if not arxiv_id:
            return None

        # 저자 목록
        authors_raw = item.get("authors", [])
        author_names = [a.get("name", "") for a in authors_raw if a.get("name")]
        if len(author_names) > 5:
            authors = ", ".join(author_names[:5]) + f" 외 {len(author_names)-5}명"
        else:
            authors = ", ".join(author_names) or "저자 정보 없음"

        # 출판일
        published_raw = item.get("publishedAt", "")
        try:
            pub_dt = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            published_at = pub_dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
        except Exception:
            published_at = datetime.now().isoformat()

        return Paper(
            arxiv_id=arxiv_id,
            title=item.get("title", "").strip().replace("\n", " "),
            authors=authors,
            abstract=item.get("summary", "").strip().replace("\n", " "),
            categories=category,
            published_at=published_at,
            arxiv_url=f"https://arxiv.org/abs/{arxiv_id}",
        )

    def collect(self) -> list[Paper]:
        """HuggingFace Papers 트렌딩 논문 수집"""
        logger.info(f"[HF] 트렌딩 논문 수집 시작 (최대 {self.limit}편, 최소 upvote: {self.min_upvotes})")
        try:
            resp = requests.get(HF_PAPERS_API, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.Timeout:
            logger.error("[HF] API 타임아웃")
            return []
        except requests.exceptions.HTTPError as e:
            logger.error(f"[HF] HTTP 오류: {e}")
            return []
        except Exception as e:
            logger.error(f"[HF] 수집 실패: {e}")
            return []

        # upvote 기준 정렬 + 필터
        items = sorted(data, key=lambda x: x.get("upvotes", 0), reverse=True)
        candidates = []
        for item in items:
            if item.get("upvotes", 0) < self.min_upvotes:
                continue
            if item.get("id", "").strip():
                candidates.append(item)
            if len(candidates) >= self.limit:
                break

        # arXiv에서 실제 카테고리 일괄 조회
        arxiv_ids = [i["id"].strip() for i in candidates]
        cat_map = self._fetch_arxiv_categories(arxiv_ids)

        papers: list[Paper] = []
        for item in candidates:
            arxiv_id = item["id"].strip()
            category = cat_map.get(arxiv_id, "cs.AI")
            paper = self._to_paper(item, category)
            if paper:
                upvotes = item.get("upvotes", 0)
                papers.append(paper)
                logger.debug(f"  ✓ [{upvotes}👍] [{category}] {arxiv_id}: {paper.title[:45]}")

        logger.info(f"[HF] 수집 완료: {len(papers)}편")
        return papers
