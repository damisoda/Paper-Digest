"""
진입점 — 파이프라인 실행 및 APScheduler 스케줄러

사용법:
  python main.py            # 스케줄러 모드 (매주 월·목 09:00 KST)
  python main.py --run-now  # 즉시 1회 실행
"""
import sys
import argparse
from datetime import datetime
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from paper_digest.config import config
from paper_digest.database import Database, Paper
from paper_digest.collectors.arxiv_collector import ArxivCollector
from paper_digest.collectors.hf_collector import HFCollector
from paper_digest.summarizer.ollama_summarizer import OllamaSummarizer
from paper_digest.outputs.obsidian_writer import ObsidianWriter
from paper_digest.outputs.discord_notifier import DiscordNotifier


# ── 로거 설정 ────────────────────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    colorize=True,
    level="INFO",
)
logger.add(
    "app.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
    level="DEBUG",
    rotation="10 MB",
    retention="30 days",
    encoding="utf-8",
)


# ── 파이프라인 ───────────────────────────────────────────────────
def run_pipeline() -> None:
    """arXiv 수집 → Ollama 요약 → DB 저장 → Obsidian 생성 → Discord 전송"""
    start = datetime.now()
    logger.info("=" * 60)
    logger.info(f"🚀 파이프라인 시작: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    try:
        config.validate()
    except ValueError as e:
        logger.error(f"설정 오류: {e}")
        return

    db = Database()
    hf_collector = HFCollector()
    arxiv_collector = ArxivCollector()
    summarizer = OllamaSummarizer()
    obsidian = ObsidianWriter(db=db)
    notifier = DiscordNotifier()

    # Step 1 — Ollama 헬스체크
    logger.info("[1/6] Ollama 상태 확인")
    if not summarizer.health_check():
        logger.error(
            f"Ollama 서버({config.OLLAMA_BASE_URL}) 또는 "
            f"'{config.OLLAMA_MODEL}' 모델을 찾을 수 없습니다.\n"
            f"  → ollama serve\n"
            f"  → ollama pull {config.OLLAMA_MODEL}"
        )
        return
    logger.success(f"[1/6] Ollama 정상 ({config.OLLAMA_MODEL})")

    # Step 2 — HuggingFace 트렌딩 논문 수집 (실패 시 arXiv로 fallback)
    logger.info("[2/6] HuggingFace 트렌딩 논문 수집")
    all_papers: list[Paper] = hf_collector.collect()
    if not all_papers:
        logger.warning("[2/6] HF 수집 0편 — arXiv 최신 논문으로 fallback")
        all_papers = arxiv_collector.collect_all()
    if not all_papers:
        logger.warning("수집된 논문 없음 (HF·arXiv 모두 실패). 종료.")
        return

    new_papers = [p for p in all_papers if not db.exists(p.arxiv_id)]
    logger.info(
        f"[2/6] 수집 {len(all_papers)}편 | 신규 {len(new_papers)}편 | "
        f"기존 {len(all_papers) - len(new_papers)}편"
    )
    if not new_papers:
        logger.info("신규 논문 없음. 종료.")
        return

    # Step 3 — Ollama 요약
    logger.info(f"[3/6] Ollama 요약 ({len(new_papers)}편)")
    summarized = summarizer.summarize_batch(new_papers)

    # Step 4 — DB 저장
    logger.info("[4/6] DB 저장")
    saved = sum(1 for p in summarized if db.save(p) is not None)
    logger.success(f"[4/6] DB 저장 완료: {saved}편 신규")

    # Step 5 — Obsidian
    logger.info("[5/6] Obsidian 저장")
    if obsidian.vault_exists():
        obs_ok, obs_skip = obsidian.write_batch(summarized)
        logger.success(f"[5/6] Obsidian 완료: 저장 {obs_ok}편 / 스킵 {obs_skip}편")
    else:
        logger.warning(f"[5/6] Vault 없음 ({obsidian.vault_path}) — 스킵")

    # Step 6 — Discord
    logger.info("[6/6] Discord 전송")
    ok, fail = notifier.send_batch(summarized)
    logger.success(f"[6/6] Discord 완료: 성공 {ok}편 / 실패 {fail}편")

    # 완료 요약
    elapsed = (datetime.now() - start).total_seconds()
    stats = db.get_stats()
    logger.info("=" * 60)
    logger.info(
        f"✅ 완료 ({elapsed:.1f}s) | DB: {stats['total']}편 "
        f"(요약 {stats['summarized']} / Obsidian {stats['obsidian_saved']})"
    )
    logger.info("=" * 60)


# ── 스케줄러 ─────────────────────────────────────────────────────
def start_scheduler() -> None:
    """매주 월·목 09:00 KST 자동 실행"""
    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        func=run_pipeline,
        trigger=CronTrigger(
            day_of_week="mon,thu",
            hour=config.SCHEDULE_HOUR,
            minute=config.SCHEDULE_MINUTE,
            timezone="Asia/Seoul",
        ),
        id="arxiv_summarizer",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    job = scheduler.get_job("arxiv_summarizer")
    next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M %Z") if job and job.next_run_time else "미정"
    logger.info("=" * 60)
    logger.info(f"⏰ 스케줄러 시작 — 매주 월·목 {config.SCHEDULE_HOUR:02d}:{config.SCHEDULE_MINUTE:02d} KST")
    logger.info(f"   다음 실행: {next_run}")
    logger.info("   종료: Ctrl+C")
    logger.info("=" * 60)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("스케줄러 종료.")


# ── 진입점 ───────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="AI 논문 자동 요약 툴")
    parser.add_argument("--run-now", action="store_true", help="즉시 1회 실행")
    args = parser.parse_args()

    if args.run_now:
        run_pipeline()
    else:
        start_scheduler()


if __name__ == "__main__":
    main()
