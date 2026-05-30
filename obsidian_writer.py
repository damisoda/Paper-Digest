"""Obsidian vault에 논문 요약 .md 파일을 자동 생성하는 모듈

그래프 구조:
  [[논문]] → [[cs.LG]] → [[개별 논문]]
           → [[cs.CL]] → [[개별 논문]]
           → [[cs.CV]] → ...
           → [[cs.AI]] → ...

저장 경로: {VAULT}/Papers/YYYY-MM/논문제목.md
노드 파일: {VAULT}/Papers/논문.md (루트)
           {VAULT}/Papers/cs.LG.md (카테고리)
"""
import re
import arxiv
from datetime import datetime
from pathlib import Path
from loguru import logger

from config import config
from database import Database, Paper


# ── 템플릿 ──────────────────────────────────────────────────────────

PAPER_TEMPLATE = """\
---
title: "{title}"
date: {date}
tags: [AI, {category}, arxiv]
arxiv: {arxiv_url}
arxiv_id: {arxiv_id}
authors: "{authors}"
published: {published_at}
---

> 분야: [[{category}]] | 원문: [{arxiv_id}]({arxiv_url})

## 📌 한 줄 요약

{summary_one_line}

## 🔍 핵심 방법

{summary_method}

## 💡 왜 중요한가

{summary_importance}

## 📊 주요 결과

{summary_results}
{grounding_note}
## ⚠️ 한계점

{summary_limitations}

## 🔗 관련 논문

{related_papers}

---
> 🤖 *AI Paper Summarizer 자동 생성*
"""

CATEGORY_LABELS = {
    "cs.LG": "Machine Learning",
    "cs.CL": "Computation & Language",
    "cs.CV": "Computer Vision",
    "cs.AI": "Artificial Intelligence",
}

_STOPWORDS = {
    "a", "an", "the", "of", "for", "in", "on", "with", "and", "or",
    "is", "are", "to", "from", "via", "using", "based", "towards", "toward", "over",
}


class ObsidianWriter:
    def __init__(self, vault_path: str = None, papers_subdir: str = None, db: Database = None):
        self.vault_path = Path(vault_path or config.OBSIDIAN_VAULT_PATH).expanduser()
        self.papers_subdir = papers_subdir or config.OBSIDIAN_PAPERS_SUBDIR
        self.related_count = config.OBSIDIAN_RELATED_COUNT
        self.db = db
        self._arxiv = arxiv.Client(page_size=self.related_count + 2, delay_seconds=2.0, num_retries=2)

    # ── 경로 헬퍼 ──────────────────────────────────────────────────

    @property
    def papers_dir(self) -> Path:
        return self.vault_path / self.papers_subdir

    def _month_dir(self, date_str: str) -> Path:
        try:
            month = datetime.fromisoformat(date_str[:10]).strftime("%Y-%m")
        except (ValueError, TypeError):
            month = datetime.now().strftime("%Y-%m")
        return self.papers_dir / month

    def _safe_name(self, title: str) -> str:
        """OS-safe 파일명 (100자 제한)"""
        s = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "", title)
        return re.sub(r"\s+", " ", s).strip(" .")[:100]

    def _file_path(self, paper: Paper) -> Path:
        return self._month_dir(paper.published_at) / (self._safe_name(paper.title) + ".md")

    # ── 관련 논문 ──────────────────────────────────────────────────

    def _fetch_related(self, paper: Paper) -> list[dict]:
        words = [
            w for w in re.sub(r"[^a-zA-Z0-9 ]", " ", paper.title).split()
            if w.lower() not in _STOPWORDS and len(w) > 2
        ]
        if not words:
            return []
        query = f"cat:{paper.categories} AND ti:{' '.join(words[:5])}"
        related = []
        try:
            search = arxiv.Search(
                query=query,
                max_results=self.related_count + 3,
                sort_by=arxiv.SortCriterion.Relevance,
            )
            for r in self._arxiv.results(search):
                rid = r.entry_id.split("/")[-1].rsplit("v", 1)[0]
                if rid == paper.arxiv_id:
                    continue
                related.append({
                    "title": r.title.strip().replace("\n", " "),
                    "arxiv_id": rid,
                    "url": r.entry_id,
                })
                if len(related) >= self.related_count:
                    break
        except Exception as e:
            logger.warning(f"[Obsidian] 관련 논문 조회 실패: {e}")
        return related

    def _fmt_related(self, related: list[dict]) -> str:
        if not related:
            return "_관련 논문을 찾지 못했습니다._"
        return "\n".join(
            f"- [[{self._safe_name(r['title'])}]] ([arXiv:{r['arxiv_id']}]({r['url']}))"
            for r in related
        )

    # ── 그래프 노드 관리 ───────────────────────────────────────────

    def _update_root_node(self, categories: set[str]) -> None:
        """루트 노드 [[논문]] 생성 / 업데이트"""
        root_path = self.papers_dir / "논문.md"
        self.papers_dir.mkdir(parents=True, exist_ok=True)

        cat_links = "\n".join(
            f"- [[{cat}]] — {CATEGORY_LABELS.get(cat, cat)}"
            for cat in sorted(categories)
        )
        content = f"""\
---
title: "논문"
tags: [AI, index]
---

# 📚 논문 아카이브

arXiv · HuggingFace Papers 트렌딩 논문 자동 요약 모음입니다.

## 카테고리

{cat_links}

---
> 🤖 *AI Paper Summarizer 자동 생성*
"""
        root_path.write_text(content, encoding="utf-8")
        logger.debug("[Obsidian] 루트 노드 업데이트: 논문.md")

    def _update_category_node(self, category: str, paper_titles: list[str]) -> None:
        """카테고리 노드 [[cs.LG]] 등 생성 / 업데이트"""
        cat_path = self.papers_dir / f"{category}.md"
        self.papers_dir.mkdir(parents=True, exist_ok=True)

        paper_links = "\n".join(
            f"- [[{self._safe_name(t)}]]" for t in paper_titles
        )
        label = CATEGORY_LABELS.get(category, category)
        content = f"""\
---
title: "{category}"
tags: [AI, category, {category}]
---

# {category} — {label}

[[논문]]

## 논문 목록

{paper_links}

---
> 🤖 *AI Paper Summarizer 자동 생성*
"""
        cat_path.write_text(content, encoding="utf-8")
        logger.debug(f"[Obsidian] 카테고리 노드 업데이트: {category}.md ({len(paper_titles)}편)")

    # ── 논문 파일 생성 ─────────────────────────────────────────────

    def _render(self, paper: Paper, related: list[dict]) -> str:
        def fill(text: str) -> str:
            return text.strip() or "_내용 없음_"

        # grounding 경고가 있으면 주요 결과 아래에 콜아웃으로 노출
        grounding = paper.grounding_note.strip()
        grounding_block = f"\n> [!warning] {grounding}\n" if grounding else ""

        return PAPER_TEMPLATE.format(
            title=paper.title.replace('"', '\\"'),
            date=datetime.now().strftime("%Y-%m-%d"),
            category=paper.categories.strip(),
            arxiv_url=paper.arxiv_url,
            arxiv_id=paper.arxiv_id,
            authors=paper.authors.replace('"', '\\"'),
            published_at=(paper.published_at or "")[:10],
            summary_one_line=fill(paper.summary_one_line),
            summary_method=fill(paper.summary_method),
            summary_importance=fill(paper.summary_importance),
            summary_results=fill(paper.summary_results),
            grounding_note=grounding_block,
            summary_limitations=fill(paper.summary_limitations),
            related_papers=self._fmt_related(related),
        )

    def write(self, paper: Paper, fetch_related: bool = True) -> str | None:
        """논문 .md 파일 저장. 중복이면 None 반환."""
        if self.db and self.db.is_obsidian_saved(paper.arxiv_id):
            logger.debug(f"[Obsidian] 스킵 (DB): {paper.arxiv_id}")
            return None

        fp = self._file_path(paper)
        if fp.exists():
            logger.debug(f"[Obsidian] 스킵 (파일 존재): {fp.name}")
            if self.db:
                self.db.update_obsidian_path(paper.arxiv_id, str(fp))
            return str(fp)

        fp.parent.mkdir(parents=True, exist_ok=True)
        related = self._fetch_related(paper) if fetch_related else []

        try:
            fp.write_text(self._render(paper, related), encoding="utf-8")
            logger.success(f"[Obsidian] 저장: {fp.name} ({fp.parent.name}/)")
        except OSError as e:
            logger.error(f"[Obsidian] 저장 실패 ({paper.arxiv_id}): {e}")
            return None

        paper.obsidian_path = str(fp)
        if self.db:
            self.db.update_obsidian_path(paper.arxiv_id, str(fp))
        return str(fp)

    def write_batch(self, papers: list[Paper]) -> tuple[int, int]:
        """여러 논문 순차 저장 후 그래프 노드 업데이트"""
        logger.info(f"[Obsidian] 배치 시작: {len(papers)}편")

        saved_papers = []
        for p in papers:
            path = self.write(p)
            if path:
                saved_papers.append(p)

        saved = len(saved_papers)
        skipped = len(papers) - saved

        # 그래프 노드 업데이트 (저장된 논문 기준)
        if saved_papers:
            self._rebuild_graph_nodes(saved_papers)

        logger.info(f"[Obsidian] 완료 — 저장 {saved}편 / 스킵 {skipped}편")
        return saved, skipped

    def _rebuild_graph_nodes(self, papers: list[Paper]) -> None:
        """카테고리별로 논문을 묶어 루트·카테고리 노드 재생성"""
        # 카테고리 → 논문 제목 맵
        cat_map: dict[str, list[str]] = {}
        for p in papers:
            cat = p.categories.strip()
            cat_map.setdefault(cat, []).append(p.title)

        # 카테고리 노드 업데이트
        for cat, titles in cat_map.items():
            self._update_category_node(cat, titles)

        # 루트 노드 업데이트
        self._update_root_node(set(cat_map.keys()))

    # ── 유틸 ──────────────────────────────────────────────────────

    def vault_exists(self) -> bool:
        return self.vault_path.exists() and self.vault_path.is_dir()

    def get_saved_files(self) -> list[Path]:
        if not self.papers_dir.exists():
            return []
        return sorted(self.papers_dir.rglob("*.md"), reverse=True)
