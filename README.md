# 📚 AI Paper Summarizer

arXiv 최신 논문을 자동 수집하고, 로컬 Ollama로 한국어 요약 후
Discord 알림 · SQLite 저장 · Obsidian 노트 생성까지 자동으로 처리하는 파이프라인입니다.

---

## 기능

| 기능 | 설명 |
|---|---|
| 논문 수집 | arXiv API — cs.LG / cs.CL / cs.CV / cs.AI |
| 한국어 요약 | 로컬 Ollama (`gemma4:e4b`) |
| Discord 알림 | 카테고리별 Embed 전송 |
| DB 저장 | SQLite (중복 방지) |
| Obsidian 연동 | vault에 `.md` 파일 자동 생성, 관련 논문 위키링크 포함 |
| 자동 실행 | APScheduler — 매주 월·목 오전 9시 (KST) |
| 대시보드 | Streamlit — 검색·열람·Obsidian 관리 |

---

## 파일 구조

```
Paper-Digest/
├── main.py               # 진입점 + APScheduler
├── config.py             # 환경변수 관리
├── database.py           # SQLite 모델 & 쿼리
├── arxiv_collector.py    # arXiv API 수집
├── ollama_summarizer.py  # Ollama 한국어 요약
├── discord_notifier.py   # Discord 웹훅 전송
├── obsidian_writer.py    # Obsidian .md 파일 생성
├── streamlit_app.py      # 웹 대시보드
├── requirements.txt      # 의존성
├── .env.example          # 환경변수 템플릿
└── .gitignore
```

---

## 빠른 시작

### 1. 패키지 설치

```bash
pip install -r requirements.txt
```

### 2. 환경변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 DISCORD_WEBHOOK_URL, OBSIDIAN_VAULT_PATH 입력
```

### 3. Ollama 준비

```bash
ollama serve              # 서버 실행
ollama pull gemma4:e4b    # 모델 다운로드
```

### 4. 실행

```bash
# 즉시 1회 실행 (테스트)
python main.py --run-now

# 스케줄러 모드 (매주 월·목 오전 9시 자동 실행)
python main.py

# 웹 대시보드
streamlit run streamlit_app.py
```

---

## 파이프라인 흐름

```
arXiv API
  └─ cs.LG / cs.CL / cs.CV / cs.AI 최신 논문 수집
       │
       ▼ (SQLite 중복 제거)
Ollama (gemma4:e4b)
  └─ 한국어 요약: 한 줄 요약 / 핵심 방법 / 왜 중요한가 / 주요 결과
       │
       ├──▶ SQLite 저장
       ├──▶ Obsidian vault → Papers/YYYY-MM/논문제목.md
       └──▶ Discord 웹훅 전송
```

---

## Obsidian 노트 형식

저장 경로: `{OBSIDIAN_VAULT_PATH}/Papers/YYYY-MM/논문제목.md`

```markdown
---
title: "논문 제목"
date: 2024-03-15
tags: [AI, cs.CL, arxiv]
arxiv: https://arxiv.org/abs/...
---

## 📌 한 줄 요약
## 🔍 핵심 방법
## 💡 왜 중요한가
## 📊 주요 결과
## 🔗 관련 논문
- [[관련 논문 제목]] (arXiv:2401.xxxxx)
```

---

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | — | **(필수)** Discord 웹훅 URL |
| `OBSIDIAN_VAULT_PATH` | `~/ObsidianVault` | Obsidian vault 경로 |
| `OBSIDIAN_PAPERS_SUBDIR` | `Papers` | vault 내 논문 저장 폴더 |
| `OBSIDIAN_RELATED_COUNT` | `3` | 관련 논문 조회 수 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 서버 주소 |
| `OLLAMA_MODEL` | `gemma4:e4b` | 사용 모델명 |
| `ARXIV_MAX_RESULTS` | `5` | 카테고리당 최대 수집 수 |
| `ARXIV_CATEGORIES` | `cs.LG,cs.CL,cs.CV,cs.AI` | 수집 카테고리 |
| `DB_PATH` | `papers.db` | SQLite 파일 경로 |

---

## Contributors

| | 이름 | 역할 |
|---|---|---|
| 👤 | [damisoda](https://github.com/damisoda) | 기획 · 설계 · 오너 |
| 🤖 | [Claude](https://claude.ai) (Anthropic) | 전체 코드 구현 · 디버깅 · 문서화 |
