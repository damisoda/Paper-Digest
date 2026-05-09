"""
SQLite 데이터베이스 관리 모듈
논문 저장, 조회, 검색, 중복 체크 기능 제공
"""

import sqlite3
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger

from config import config


@dataclass
class Paper:
    """논문 데이터 모델"""
    arxiv_id: str
    title: str
    authors: str
    abstract: str
    categories: str
    published_at: str
    arxiv_url: str
    summary_one_line: str = ""       # 📌 한 줄 요약
    summary_method: str = ""         # 🔍 핵심 방법
    summary_importance: str = ""     # 💡 왜 중요한가
    summary_results: str = ""        # 📊 주요 결과
    raw_summary: str = ""            # Ollama 원본 응답
    obsidian_path: str = ""          # Obsidian .md 파일 경로 (저장 완료 시 기록)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    id: Optional[int] = None


class Database:
    """SQLite 데이터베이스 관리 클래스"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DB_PATH
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """DB 연결 반환 (Row 팩토리 포함)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """테이블 초기화 (없으면 생성) + 기존 테이블 마이그레이션"""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS papers (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    arxiv_id          TEXT UNIQUE NOT NULL,
                    title             TEXT NOT NULL,
                    authors           TEXT,
                    abstract          TEXT,
                    categories        TEXT,
                    published_at      TEXT,
                    arxiv_url         TEXT,
                    summary_one_line  TEXT DEFAULT '',
                    summary_method    TEXT DEFAULT '',
                    summary_importance TEXT DEFAULT '',
                    summary_results   TEXT DEFAULT '',
                    raw_summary       TEXT DEFAULT '',
                    obsidian_path     TEXT DEFAULT '',
                    created_at        TEXT NOT NULL
                )
            """)
            # 기존 DB에 obsidian_path 컬럼이 없으면 마이그레이션
            existing_cols = [
                row[1]
                for row in conn.execute("PRAGMA table_info(papers)").fetchall()
            ]
            if "obsidian_path" not in existing_cols:
                conn.execute(
                    "ALTER TABLE papers ADD COLUMN obsidian_path TEXT DEFAULT ''"
                )
                logger.info("[DB] 마이그레이션: obsidian_path 컬럼 추가")

            # 검색 성능을 위한 인덱스 생성
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_published_at ON papers (published_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_categories ON papers (categories)"
            )
            conn.commit()
        logger.info(f"DB 초기화 완료: {self.db_path}")

    def exists(self, arxiv_id: str) -> bool:
        """arXiv ID 기반 중복 여부 확인"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM papers WHERE arxiv_id = ?", (arxiv_id,)
            ).fetchone()
        return row is not None

    def save(self, paper: Paper) -> Optional[int]:
        """
        논문 저장. 이미 존재하면 요약 내용만 업데이트.
        Returns: 삽입된 row id (업데이트 시 None)
        """
        if self.exists(paper.arxiv_id):
            # 비어있는 필드만 업데이트 (요약 + obsidian_path)
            with self._get_conn() as conn:
                conn.execute("""
                    UPDATE papers SET
                        summary_one_line   = CASE WHEN summary_one_line = '' THEN ? ELSE summary_one_line END,
                        summary_method     = CASE WHEN summary_method = '' THEN ? ELSE summary_method END,
                        summary_importance = CASE WHEN summary_importance = '' THEN ? ELSE summary_importance END,
                        summary_results    = CASE WHEN summary_results = '' THEN ? ELSE summary_results END,
                        raw_summary        = CASE WHEN raw_summary = '' THEN ? ELSE raw_summary END,
                        obsidian_path      = CASE WHEN obsidian_path = '' THEN ? ELSE obsidian_path END
                    WHERE arxiv_id = ?
                """, (
                    paper.summary_one_line,
                    paper.summary_method,
                    paper.summary_importance,
                    paper.summary_results,
                    paper.raw_summary,
                    paper.obsidian_path,
                    paper.arxiv_id,
                ))
                conn.commit()
            logger.debug(f"[DB] 기존 논문 업데이트: {paper.arxiv_id}")
            return None

        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO papers (
                    arxiv_id, title, authors, abstract, categories,
                    published_at, arxiv_url, summary_one_line, summary_method,
                    summary_importance, summary_results, raw_summary,
                    obsidian_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                paper.arxiv_id,
                paper.title,
                paper.authors,
                paper.abstract,
                paper.categories,
                paper.published_at,
                paper.arxiv_url,
                paper.summary_one_line,
                paper.summary_method,
                paper.summary_importance,
                paper.summary_results,
                paper.raw_summary,
                paper.obsidian_path,
                paper.created_at,
            ))
            conn.commit()
            logger.info(f"[DB] 새 논문 저장: {paper.arxiv_id} | {paper.title[:50]}")
            return cursor.lastrowid

    def get_all(
        self,
        limit: int = 100,
        offset: int = 0,
        category: str = None,
    ) -> list[dict]:
        """전체 논문 목록 조회 (최신순)"""
        query = "SELECT * FROM papers"
        params = []

        if category:
            query += " WHERE categories LIKE ?"
            params.append(f"%{category}%")

        query += " ORDER BY published_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def search(self, keyword: str, limit: int = 50) -> list[dict]:
        """
        키워드로 제목/초록/요약 전체 검색
        """
        query = """
            SELECT * FROM papers
            WHERE title LIKE ?
               OR abstract LIKE ?
               OR summary_one_line LIKE ?
               OR summary_method LIKE ?
               OR summary_importance LIKE ?
               OR summary_results LIKE ?
            ORDER BY published_at DESC
            LIMIT ?
        """
        kw = f"%{keyword}%"
        with self._get_conn() as conn:
            rows = conn.execute(query, (kw, kw, kw, kw, kw, kw, limit)).fetchall()
        return [dict(row) for row in rows]

    def update_obsidian_path(self, arxiv_id: str, obsidian_path: str) -> None:
        """arXiv ID에 해당하는 논문의 Obsidian 파일 경로를 업데이트"""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE papers SET obsidian_path = ? WHERE arxiv_id = ?",
                (obsidian_path, arxiv_id),
            )
            conn.commit()
        logger.debug(f"[DB] obsidian_path 업데이트: {arxiv_id} → {obsidian_path}")

    def is_obsidian_saved(self, arxiv_id: str) -> bool:
        """해당 논문이 Obsidian에 이미 저장됐는지 확인"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT obsidian_path FROM papers WHERE arxiv_id = ?",
                (arxiv_id,),
            ).fetchone()
        return bool(row and row[0])

    def get_stats(self) -> dict:
        """통계 정보 반환"""
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
            summarized = conn.execute(
                "SELECT COUNT(*) FROM papers WHERE summary_one_line != ''"
            ).fetchone()[0]
            obsidian_saved = conn.execute(
                "SELECT COUNT(*) FROM papers WHERE obsidian_path != ''"
            ).fetchone()[0]
            latest = conn.execute(
                "SELECT published_at FROM papers ORDER BY published_at DESC LIMIT 1"
            ).fetchone()

        return {
            "total": total,
            "summarized": summarized,
            "unsummarized": total - summarized,
            "obsidian_saved": obsidian_saved,
            "latest_date": latest[0] if latest else "없음",
        }

    def count(self, category: str = None) -> int:
        """논문 수 (category 지정 시 해당 카테고리만 집계)"""
        with self._get_conn() as conn:
            if category:
                return conn.execute(
                    "SELECT COUNT(*) FROM papers WHERE categories LIKE ?",
                    (f"%{category}%",),
                ).fetchone()[0]
            return conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
