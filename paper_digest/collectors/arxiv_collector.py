"""arXiv API로 최신 논문을 수집하는 모듈"""
import arxiv
from datetime import datetime, timezone
from loguru import logger

from paper_digest.config import config
from paper_digest.database import Paper


class ArxivCollector:
    def __init__(self, categories: list[str] = None, max_results: int = None):
        self.categories = categories or config.ARXIV_CATEGORIES
        self.max_results = max_results or config.ARXIV_MAX_RESULTS
        self.client = arxiv.Client(
            page_size=self.max_results,
            delay_seconds=3.0,
            num_retries=3,
        )

    def _to_paper(self, result: arxiv.Result, category: str) -> Paper:
        """arxiv.Result → Paper 변환"""
        arxiv_id = result.entry_id.split("/")[-1]
        if "v" in arxiv_id:
            arxiv_id = arxiv_id.rsplit("v", 1)[0]

        authors = ", ".join(a.name for a in result.authors[:5])
        if len(result.authors) > 5:
            authors += f" 외 {len(result.authors) - 5}명"

        pub = result.published
        if pub and pub.tzinfo:
            pub = pub.astimezone(timezone.utc).replace(tzinfo=None)

        return Paper(
            arxiv_id=arxiv_id,
            title=result.title.strip().replace("\n", " "),
            authors=authors,
            abstract=result.summary.strip().replace("\n", " "),
            categories=category,
            published_at=pub.isoformat() if pub else "",
            arxiv_url=result.entry_id,
        )

    def collect_by_category(self, category: str) -> list[Paper]:
        """특정 카테고리의 최신 논문 수집"""
        logger.info(f"[arXiv] {category} 수집 시작 (최대 {self.max_results}편)")
        papers = []
        try:
            search = arxiv.Search(
                query=f"cat:{category}",
                max_results=self.max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )
            for result in self.client.results(search):
                paper = self._to_paper(result, category)
                papers.append(paper)
                logger.debug(f"  ✓ {paper.arxiv_id}: {paper.title[:60]}")
        except Exception as e:
            logger.error(f"[arXiv] {category} 수집 실패: {e}")

        logger.info(f"[arXiv] {category} 완료: {len(papers)}편")
        return papers

    def collect_all(self) -> list[Paper]:
        """모든 카테고리에서 논문 수집 (중복 arXiv ID 제거)"""
        logger.info(f"[arXiv] 수집 시작 — 카테고리: {self.categories}")
        seen: dict[str, Paper] = {}
        for category in self.categories:
            for paper in self.collect_by_category(category):
                if paper.arxiv_id not in seen:
                    seen[paper.arxiv_id] = paper

        result = list(seen.values())
        logger.info(f"[arXiv] 전체 완료: {len(result)}편 (중복 제거 후)")
        return result
