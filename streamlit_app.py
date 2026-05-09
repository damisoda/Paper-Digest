"""Streamlit 대시보드 — 논문 열람·검색·Obsidian 관리

실행: streamlit run streamlit_app.py
"""
import subprocess
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime

from config import config
from database import Database, Paper
from obsidian_writer import ObsidianWriter


# ── 페이지 설정 ──────────────────────────────────────────────────
st.set_page_config(
    page_title="AI 논문 요약 대시보드",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .paper-title { font-size: 1.1em; font-weight: 700; }
    .paper-meta  { font-size: 0.85em; color: #a6adc8; margin-top: 4px; }
    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.8em;
        font-weight: 600;
        margin-right: 4px;
    }
</style>
""", unsafe_allow_html=True)

CATEGORY_COLORS = {
    "cs.LG": "#5865F2",
    "cs.CL": "#57F287",
    "cs.CV": "#FEE75C",
    "cs.AI": "#ED4245",
}


# ── 리소스 캐시 ──────────────────────────────────────────────────
@st.cache_resource
def get_db() -> Database:
    return Database(config.DB_PATH)


@st.cache_resource
def get_obsidian() -> ObsidianWriter:
    return ObsidianWriter(db=get_db())


# ── 논문 카드 ────────────────────────────────────────────────────
def render_card(paper: dict) -> None:
    cat = paper.get("categories", "").strip()
    color = CATEGORY_COLORS.get(cat, "#99AAB5")
    pub_date = (paper.get("published_at") or "")[:10]
    arxiv_url = paper.get("arxiv_url", "#")
    title = paper.get("title", "제목 없음")
    authors = paper.get("authors", "저자 정보 없음")
    arxiv_id = paper.get("arxiv_id", "")
    obsidian_path = paper.get("obsidian_path", "")

    # 뱃지
    badges = (
        f'<span class="badge" style="background:{color}22;color:{color};border:1px solid {color};">{cat}</span>'
    )
    if obsidian_path:
        badges += '<span class="badge" style="background:#7c3aed22;color:#a78bfa;border:1px solid #7c3aed;">🗒️ Obsidian</span>'

    st.markdown(badges, unsafe_allow_html=True)
    st.markdown(
        f'<div class="paper-title"><a href="{arxiv_url}" target="_blank" style="color:#89b4fa;text-decoration:none;">{title}</a></div>'
        f'<div class="paper-meta">👥 {authors} &nbsp;|&nbsp; 📅 {pub_date} &nbsp;|&nbsp; 🔗 arXiv:{arxiv_id}</div>',
        unsafe_allow_html=True,
    )

    one_line = paper.get("summary_one_line", "")
    method = paper.get("summary_method", "")
    importance = paper.get("summary_importance", "")
    results = paper.get("summary_results", "")
    has_summary = any([one_line, method, importance, results])

    with st.expander("📋 요약 보기" if has_summary else "⏳ 요약 없음"):
        if has_summary:
            sections = [
                ("📌", "한 줄 요약", one_line),
                ("🔍", "핵심 방법", method),
                ("💡", "왜 중요한가", importance),
                ("📊", "주요 결과", results),
            ]
            # 실제 내용이 있는 항목만 추려서 마지막에만 divider 생략
            filled = [(e, l, t) for e, l, t in sections if t]
            for idx, (emoji, label, text) in enumerate(filled):
                st.markdown(f"**{emoji} {label}**\n\n{text}")
                if idx < len(filled) - 1 or obsidian_path:
                    st.divider()
            if obsidian_path:
                st.markdown(f"**🗒️ Obsidian 저장 경로**\n\n`{obsidian_path}`")
        else:
            abstract = paper.get("abstract", "")
            st.caption("요약이 아직 생성되지 않았습니다.")
            if abstract:
                st.text(abstract[:600] + ("..." if len(abstract) > 600 else ""))

    st.divider()


# ── 메인 ─────────────────────────────────────────────────────────
def main() -> None:
    db = get_db()
    obsidian = get_obsidian()
    stats = db.get_stats()

    # ── 사이드바 ─────────────────────────────────────────────────
    with st.sidebar:
        st.title("📚 AI 논문 요약")
        st.caption("arXiv 최신 논문 자동 요약 대시보드")
        st.divider()

        st.metric("전체 논문", f"{stats['total']}편")
        st.metric("요약 완료", f"{stats['summarized']}편")
        st.metric("요약 대기", f"{stats['unsummarized']}편")
        st.metric("🗒️ Obsidian 저장", f"{stats.get('obsidian_saved', 0)}편")
        st.caption(f"최신: {stats['latest_date'][:10] if stats['latest_date'] != '없음' else '없음'}")
        st.divider()

        st.subheader("🗒️ Obsidian")
        if obsidian.vault_exists():
            st.success("Vault 연결됨")
            st.caption(f"저장된 .md: {len(obsidian.get_saved_files())}개")
        else:
            st.error("Vault 경로 없음")
        st.caption(f"`{obsidian.vault_path}`")
        st.divider()

        st.subheader("🔍 필터")
        selected_cat = st.selectbox("카테고리", ["전체", "cs.LG", "cs.CL", "cs.CV", "cs.AI"])
        only_summarized = st.checkbox("요약된 논문만 보기")
        per_page = st.slider("페이지당 논문 수", 5, 50, 10, step=5)
        st.divider()

        st.subheader("⚙️ 실행")
        if st.button("🚀 지금 수집·요약 실행", use_container_width=True):
            with st.spinner("파이프라인 실행 중..."):
                try:
                    result = subprocess.run(
                        [sys.executable, "main.py", "--run-now"],
                        capture_output=True, text=True, timeout=600,
                    )
                    if result.returncode == 0:
                        st.success("완료! 새로고침하세요.")
                    else:
                        st.error(f"오류:\n{result.stderr[-500:]}")
                except Exception as e:
                    st.error(f"실행 실패: {e}")

    # ── 메인 영역 ─────────────────────────────────────────────────
    st.title("📰 AI 논문 자동 요약 대시보드")

    search = st.text_input("🔎 논문 검색", placeholder="제목, 저자, 키워드, 요약 내용...")

    tab_list, tab_obsidian, tab_stats = st.tabs(["📋 논문 목록", "🗒️ Obsidian", "📊 통계"])

    # ── 탭 1: 논문 목록 ─────────────────────────────────────────
    with tab_list:
        if "page" not in st.session_state:
            st.session_state.page = 0

        cat_filter = None if selected_cat == "전체" else selected_cat

        if search.strip():
            papers = db.search(search.strip(), limit=200)
            if cat_filter:
                papers = [p for p in papers if p["categories"] == cat_filter]
            st.caption(f'🔍 "{search}" 검색 결과: {len(papers)}편')
            st.session_state.page = 0
        elif only_summarized:
            papers = db.get_all(limit=1000, category=cat_filter)
            papers = [p for p in papers if p.get("summary_one_line")]
        else:
            papers = db.get_all(
                limit=per_page,
                offset=st.session_state.page * per_page,
                category=cat_filter,
            )

        if not papers:
            st.info("표시할 논문이 없습니다. 먼저 논문을 수집해주세요.")
        else:
            if not search.strip() and not only_summarized:
                # 카테고리 필터가 걸려 있으면 필터된 수로 페이지 계산
                total = db.count(category=cat_filter)
                total_pages = max(1, (total + per_page - 1) // per_page)
                col_prev, col_info, col_next = st.columns([1, 3, 1])
                with col_prev:
                    if st.button("◀ 이전", disabled=(st.session_state.page == 0)):
                        st.session_state.page -= 1
                        st.rerun()
                with col_info:
                    st.markdown(
                        f"<div style='text-align:center;padding:6px;'>페이지 "
                        f"{st.session_state.page + 1} / {total_pages} (전체 {total}편)</div>",
                        unsafe_allow_html=True,
                    )
                with col_next:
                    if st.button("다음 ▶", disabled=(st.session_state.page >= total_pages - 1)):
                        st.session_state.page += 1
                        st.rerun()

            for paper in papers:
                render_card(paper)

    # ── 탭 2: Obsidian ───────────────────────────────────────────
    with tab_obsidian:
        st.subheader("🗒️ Obsidian Vault 현황")

        if not obsidian.vault_exists():
            st.error(
                f"Vault 경로를 찾을 수 없습니다: `{obsidian.vault_path}`\n\n"
                "`.env`의 `OBSIDIAN_VAULT_PATH`를 확인해주세요."
            )
        else:
            c1, c2 = st.columns(2)
            c1.info(f"**Vault**\n\n`{obsidian.vault_path}`")
            c2.info(f"**논문 폴더**\n\n`{obsidian.vault_path / obsidian.papers_subdir}`")

            saved_files = obsidian.get_saved_files()
            st.markdown(f"**저장된 .md 파일: {len(saved_files)}개**")

            if saved_files:
                groups: dict[str, list[Path]] = {}
                for f in saved_files:
                    groups.setdefault(f.parent.name, []).append(f)

                first_month = sorted(groups.keys(), reverse=True)[0]
                for month, files in sorted(groups.items(), reverse=True):
                    with st.expander(f"📁 {month} — {len(files)}개", expanded=(month == first_month)):
                        for f in files:
                            col_name, col_btn = st.columns([7, 3])
                            col_name.markdown(f"📄 `{f.stem}`")
                            if col_btn.button("미리보기", key=f"prev_{month}_{f.stem}"):
                                try:
                                    content = f.read_text(encoding="utf-8")
                                    st.code(content[:1500] + ("..." if len(content) > 1500 else ""), language="markdown")
                                except Exception as e:
                                    st.error(f"읽기 실패: {e}")
            else:
                st.info("저장된 .md 파일이 없습니다.")

            st.divider()
            st.subheader("🔄 미저장 논문 수동 저장")
            unsaved = [
                p for p in db.get_all(limit=1000)
                if not p.get("obsidian_path") and p.get("summary_one_line")
            ]
            st.caption(f"요약 완료 & Obsidian 미저장: {len(unsaved)}편")

            if unsaved and st.button(f"📥 {len(unsaved)}편 저장", use_container_width=True):
                progress = st.progress(0)
                status = st.empty()
                ok = 0
                for i, p_dict in enumerate(unsaved):
                    paper_obj = Paper(**{
                        k: p_dict.get(k, "")
                        for k in Paper.__dataclass_fields__
                        if k != "id"
                    })
                    paper_obj.id = p_dict.get("id")
                    if obsidian.write(paper_obj):
                        ok += 1
                    progress.progress((i + 1) / len(unsaved))
                    status.text(f"{i + 1}/{len(unsaved)} 처리 중...")
                st.success(f"✅ {ok}편 저장 완료! 새로고침하세요.")

    # ── 탭 3: 통계 ──────────────────────────────────────────────
    with tab_stats:
        st.subheader("📊 수집 통계")
        all_papers = db.get_all(limit=10000)
        if not all_papers:
            st.info("데이터가 없습니다.")
        else:
            df = pd.DataFrame(all_papers)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("전체 논문", len(df))
            c2.metric("요약 완료", (df["summary_one_line"] != "").sum())
            c3.metric("Obsidian 저장", (df["obsidian_path"] != "").sum())
            _latest = df["published_at"].dropna().max()
            c4.metric("최신 논문", _latest[:10] if _latest else "-")
            st.divider()

            col_a, col_b = st.columns(2)
            with col_a:
                st.subheader("카테고리별 논문 수")
                counts = df["categories"].value_counts().rename_axis("카테고리").reset_index(name="논문 수")
                st.bar_chart(counts.set_index("카테고리"))

            with col_b:
                st.subheader("날짜별 수집 추이 (최근 30일)")
                df["date"] = df["published_at"].str[:10]
                date_counts = df.groupby("date").size().reset_index(name="논문 수").tail(30)
                st.line_chart(date_counts.set_index("date"))

            st.subheader("최근 수집 논문 (상위 20편)")
            cols = ["arxiv_id", "title", "categories", "published_at", "authors"]
            st.dataframe(
                df[[c for c in cols if c in df.columns]].head(20),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "arxiv_id": st.column_config.TextColumn("arXiv ID", width=120),
                    "title": st.column_config.TextColumn("제목", width=400),
                    "categories": st.column_config.TextColumn("카테고리", width=100),
                    "published_at": st.column_config.TextColumn("출판일", width=120),
                    "authors": st.column_config.TextColumn("저자", width=200),
                },
            )


if __name__ == "__main__":
    main()
