"""전역 설정 — 환경변수를 읽어 프로젝트 전체에 제공"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Discord
    DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")

    # Ollama
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
    OLLAMA_TIMEOUT: int = int(os.getenv("OLLAMA_TIMEOUT", "120"))

    # arXiv
    ARXIV_MAX_RESULTS: int = int(os.getenv("ARXIV_MAX_RESULTS", "5"))
    ARXIV_CATEGORIES: list[str] = os.getenv(
        "ARXIV_CATEGORIES", "cs.LG,cs.CL,cs.CV,cs.AI"
    ).split(",")

    # SQLite
    DB_PATH: str = os.getenv("DB_PATH", "papers.db")

    # Obsidian
    OBSIDIAN_VAULT_PATH: str = os.path.expanduser(
        os.getenv("OBSIDIAN_VAULT_PATH", "~/ObsidianVault")
    )
    OBSIDIAN_PAPERS_SUBDIR: str = os.getenv("OBSIDIAN_PAPERS_SUBDIR", "Papers")
    OBSIDIAN_RELATED_COUNT: int = int(os.getenv("OBSIDIAN_RELATED_COUNT", "3"))

    # 스케줄 — 매주 월·목 09:00 KST
    SCHEDULE_HOUR: int = 9
    SCHEDULE_MINUTE: int = 0

    @classmethod
    def validate(cls) -> None:
        """필수 환경변수 누락 시 ValueError"""
        if not cls.DISCORD_WEBHOOK_URL:
            raise ValueError(
                "DISCORD_WEBHOOK_URL이 설정되지 않았습니다.\n"
                ".env 파일에 DISCORD_WEBHOOK_URL을 추가해주세요."
            )


config = Config()
