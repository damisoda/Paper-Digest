"""Discord 웹훅으로 논문 요약을 Embed 형식으로 전송하는 모듈"""
import requests
from datetime import datetime, timezone
from loguru import logger

from config import config
from database import Paper


CATEGORY_COLORS = {
    "cs.LG": 0x5865F2,
    "cs.CL": 0x57F287,
    "cs.CV": 0xFEE75C,
    "cs.AI": 0xED4245,
}
CATEGORY_EMOJI = {
    "cs.LG": "🤖",
    "cs.CL": "💬",
    "cs.CV": "👁️",
    "cs.AI": "🧠",
}
DEFAULT_COLOR = 0x99AAB5


class DiscordNotifier:
    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url or config.DISCORD_WEBHOOK_URL

    def _post(self, payload: dict) -> bool:
        """웹훅에 페이로드 전송, 성공 여부 반환"""
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            if resp.status_code in (200, 204):
                return True
            logger.error(f"[Discord] HTTP {resp.status_code}: {resp.text}")
            return False
        except requests.exceptions.ConnectionError:
            logger.error("[Discord] 연결 실패 — 웹훅 URL을 확인하세요.")
            return False
        except requests.exceptions.Timeout:
            logger.error("[Discord] 요청 타임아웃")
            return False

    def _build_embed(self, paper: Paper) -> dict:
        """Paper → Discord Embed 딕셔너리"""
        cat = paper.categories.strip()
        sections = []
        if paper.summary_one_line:
            sections.append(f"📌 **한 줄 요약**\n{paper.summary_one_line}")
        if paper.summary_method:
            sections.append(f"🔍 **핵심 방법**\n{paper.summary_method}")
        if paper.summary_importance:
            sections.append(f"💡 **왜 중요한가**\n{paper.summary_importance}")
        if paper.summary_results:
            sections.append(f"📊 **주요 결과**\n{paper.summary_results}")

        description = "\n\n".join(sections) or "요약 없음"
        if len(description) > 4000:
            description = description[:3997] + "..."

        return {
            "title": paper.title[:256],
            "url": paper.arxiv_url,
            "description": description,
            "color": CATEGORY_COLORS.get(cat, DEFAULT_COLOR),
            "fields": [
                {"name": "👥 저자", "value": paper.authors[:1024] or "없음", "inline": True},
                {"name": "🏷️ 카테고리", "value": cat, "inline": True},
                {"name": "📅 출판일", "value": (paper.published_at or "")[:10] or "없음", "inline": True},
            ],
            "footer": {"text": f"arXiv:{paper.arxiv_id} • AI Paper Summarizer"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def send_paper(self, paper: Paper) -> bool:
        """논문 한 편 전송"""
        ok = self._post({"embeds": [self._build_embed(paper)]})
        if ok:
            logger.success(f"[Discord] 전송: {paper.arxiv_id}")
        return ok

    def send_batch(self, papers: list[Paper]) -> tuple[int, int]:
        """카테고리별로 묶어 배치 전송 (embed 최대 10개/요청)
        Returns: (성공 수, 실패 수)
        """
        if not papers:
            return 0, 0

        self._post({
            "content": (
                f"📚 **AI 논문 요약 리포트** — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"총 **{len(papers)}편** 요약을 전송합니다."
            )
        })

        # 카테고리별 그룹핑
        groups: dict[str, list[Paper]] = {}
        for p in papers:
            groups.setdefault(p.categories.strip(), []).append(p)

        success, fail = 0, 0
        for cat, cat_papers in groups.items():
            emoji = CATEGORY_EMOJI.get(cat, "📄")
            self._post({"content": f"{emoji} **[{cat}]** — {len(cat_papers)}편"})

            for i in range(0, len(cat_papers), 10):
                chunk = cat_papers[i:i + 10]
                if self._post({"embeds": [self._build_embed(p) for p in chunk]}):
                    success += len(chunk)
                    logger.info(f"[Discord] [{cat}] {i + len(chunk)}/{len(cat_papers)}편 전송")
                else:
                    fail += len(chunk)

        status = "✅" if fail == 0 else "⚠️"
        self._post({"content": f"{status} 완료: 성공 **{success}편**, 실패 **{fail}편**\n{'─' * 33}"})
        logger.info(f"[Discord] 배치 완료: 성공 {success}, 실패 {fail}")
        return success, fail
