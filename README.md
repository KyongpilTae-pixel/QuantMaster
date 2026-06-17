# QuantMaster Pro v2.0

**Hybrid Quant & Technical Breakout Scanner**

한국(KOSPI/KOSDAQ) 및 미국(S&P500/NASDAQ) 주식에서 퀀트 지표(PBR, ROE)와 기술적 지표(VWAP, MFI, OBV)를 결합해 매수 후보를 자동 발굴하는 스캐너. Reflex 기반 웹 UI로 스캔 결과, 투자 근거, 가격 차트, 백테스트 결과를 제공한다.

---

## 목차

- [아키텍처](#아키텍처)
- [스캔 로직](#스캔-로직)
- [파일별 설명](#파일별-설명)
- [설치 방법](#설치-방법)
- [실행 방법](#실행-방법)
- [테스트](#테스트)
- [화면 구성](#화면-구성)

---

## 아키텍처

```
[ NAVER Finance ]      ──PBR/ROE (한국)──►
[ FinanceDataReader ]  ─────OHLCV────────►  data_loader.py
[ yfinance ]           ──PBR/ROE (미국)──►
                                                  │
                                         indicators.py  (VWAP · MFI · OBV · TWAP)
                                                  │
                                         scanner.py  ◄── 3단계 필터 + 자동 완화
                                         backtester.py ◄── VWAP 전략 시뮬레이션
                                                  │
                                         reasoning.py  (매수 근거 · 매도 가이드 생성)
                                                  │
                                         main/main.py  (Reflex UI)
                                                  │
                                 ┌────────────────┼────────────────┐
                            [스캐너 탭]      [분석 탭]       [백테스트 탭]
```

**데이터 흐름**

| 시장 | 기본 데이터 | OHLCV |
|------|------------|-------|
| KOSPI / KOSDAQ | NAVER Finance 스크래핑 (PBR · ROE) | FinanceDataReader |
| S&P 500 / NASDAQ | yfinance 병렬 조회 (PBR · ROE) | FinanceDataReader |

---

## 스캔 로직

### 3단계 필터

| 단계 | 분류 | 조건 |
|------|------|------|
| 1 | Quant | PBR ≤ 설정값 & ROE 백분위 ≥ 임계값 (GP/A 프록시) |
| 2 | Technical | 종가 > VWAP_{기간} |
| 3 | Momentum | MFI > 임계값 & OBV > OBV_Signal |

### 자동 임계값 완화 (결과 < 10개일 때)

| 완화 단계 | PBR 한도 | GPA 최소 | MFI 최소 | OBV 필수 |
|-----------|---------|---------|---------|---------|
| 1 원본 | 사용자 설정 | 60% | 50 | ✓ |
| 2 PBR완화 | max(설정, 1.5) | 40% | 45 | ✓ |
| 3 GPA완화 | max(설정, 2.0) | 20% | 45 | ✓ |
| 4 OBV제외 | 2.0 | 0% | 45 | ✗ |
| 5 MFI완화 | 2.0 | 0% | 40 | ✗ |

각 종목에 어느 단계에서 통과했는지 `Condition` 컬럼으로 표시된다.

---

## 파일별 설명

```
QuantMaster/
├── main/
│   ├── __init__.py
│   └── main.py          # Reflex UI 앱 (State · 컴포넌트 · 이벤트 핸들러)
├── utils/
│   ├── __init__.py
│   ├── data_loader.py   # 시장 데이터 수집 (NAVER Finance + FinanceDataReader + yfinance)
│   ├── indicators.py    # 기술적 지표 계산 (VWAP · TWAP · MFI · OBV)
│   ├── reasoning.py     # 매수 근거 · 매도 가이드 텍스트 생성 (KRW/USD 지원)
│   └── scan_db.py       # SQLite CRUD (스캔 저장 · 히스토리 · 보유 종목)
├── scanner.py           # 3단계 하이브리드 스캔 + 자동 임계값 완화
├── backtester.py        # VWAP 돌파 전략 백테스트 (MDD · Sharpe · 승률)
├── rxconfig.py          # Reflex 설정 (app_name = "main")
├── requirements.txt     # Python 의존성
├── tests/
│   ├── conftest.py           # pytest fixtures (ohlcv_uptrend · downtrend · flat)
│   ├── test_indicators.py    # TechnicalIndicators 단위 테스트 (15건)
│   ├── test_backtester.py    # Backtester 단위 테스트 (13건)
│   ├── test_scanner.py       # QuantScanner 단위 테스트 mock (10건)
│   ├── test_scan_db.py       # scan_db CRUD 단위 테스트 (41건, 보유 종목 포함)
│   └── test_data_loader.py   # 통합 테스트 (실제 네트워크, @integration 마크)
└── .gitignore
```

### `utils/data_loader.py`
- `QuantDataLoader.get_market_snapshot(market, max_pages)` — 시장별 분기:
  - **KOSPI/KOSDAQ**: NAVER Finance 시가총액 페이지 스크래핑 (pykrx KRX API 연결 불가 문제로 대체)
  - **SP500/NASDAQ**: FinanceDataReader로 구성종목 목록 조회 후 yfinance로 PBR·ROE 병렬 수집 (ThreadPoolExecutor, max_workers=8)
- `QuantDataLoader.get_ohlcv(symbol, lookback_days)` — FinanceDataReader로 OHLCV 반환 (한국/미국 공통).

### `utils/indicators.py`
- `TechnicalIndicators.calculate_all(df, windows)` — VWAP · TWAP (복수 기간) · MFI(14일) · OBV · OBV_Signal(20일 MA) 계산.
- MFI 엣지 케이스 처리: 순수 상승 추세 → MFI=100, 횡보 → MFI=50.

### `utils/reasoning.py`
- `InvestmentReasoning.generate_report(name, pbr, vwap_p, mfi, vwap_price, currency)` — KRW/USD에 맞는 가격 포맷으로 매수 근거 / 매도 가이드 생성.

### `scanner.py`
- `QuantScanner.run_advanced_scan(target_pbr, vwap_period, min_count, market)` — 3단계 필터 + 5단계 자동 완화 스캔.
- 결과 DataFrame: `Applied_PBR / Applied_GPA / Applied_MFI / Applied_OBV / Condition / Currency`.

### `backtester.py`
- `Backtester.run(symbol, name, vwap_period, initial_capital)` — VWAP 돌파 진입 / VWAP 이탈 청산 전략 시뮬레이션.
- 반환: 총수익률 · MDD · 승률 · 평균수익 · Sharpe · 자본금 추이 · 매매 내역.

### `utils/scan_db.py`
- `save_scan / load_scan_results / load_run_list` — 퀀트 스캔 결과 SQLite 저장·로드.
- `save_whale_scan / load_whale_results` — 세력 탐지 결과 저장·로드.
- `add_holding / load_holdings / remove_holding / is_holding` — 보유 종목 CRUD.

### `main/main.py`
- `State` — Reflex 앱 상태 (스캔 결과 · 선택 종목 메타 · 차트 데이터 · 백테스트 요약 · 보유 종목 · 포트폴리오 집계).
- `run_scan()` — 비동기 스캔 실행, 진행 상태 실시간 업데이트.
- `select_stock()` — 종목 선택 시 투자 근거 생성 + 차트 데이터 비동기 로드 + selected_* 메타 저장.
- `run_backtest()` — 선택 종목 백테스트 비동기 실행.
- `add_to_holdings()` — 분석 탭에서 현재 종목을 보유 목록에 등록.
- `remove_holding()` — 보유 종목 삭제 후 포트폴리오 집계 재계산.
- `select_holding_for_analysis()` — 보유종목 탭에서 분석 탭으로 이동.
- `load_holdings_from_db()` — DB에서 보유 종목 로드 + 종목별 투자금/손익/손익률 계산 + 포트폴리오 집계(총 투자금·총 손익·손익률) 갱신.

---

## 설치 방법

### 사전 요구사항

- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) 또는 Anaconda
- Node.js 20+
- Git

### 환경 설정

```bash
# 1. 저장소 클론
git clone https://github.com/KyongpilTae-pixel/QuantMaster.git
cd QuantMaster

# 2. conda 환경 생성 (Python 3.11 권장)
conda create -n quantmaster python=3.11 -y
conda activate quantmaster

# 3. 의존성 설치
pip install -r requirements.txt
```

### 의존성 목록 (`requirements.txt`)

| 패키지 | 용도 |
|--------|------|
| `pandas` / `numpy` | 데이터 처리 |
| `finance-datareader` | OHLCV 및 미국 구성종목 리스트 |
| `yfinance` | 미국 주식 기본 데이터 (PBR, ROE) |
| `requests` / `beautifulsoup4` / `lxml` | NAVER Finance 스크래핑 |
| `reflex` | 웹 UI 프레임워크 |
| `pytest` | 단위 테스트 |

---

## 실행 방법

```bash
conda activate quantmaster
cd QuantMaster

# Reflex 초기화 (최초 1회)
reflex init

# 개발 서버 실행
reflex run
```

브라우저에서 **http://localhost:3000** 접속.

> Windows에서 `reflex` 명령이 없다면 전체 경로 사용:
> `C:\Users\<사용자명>\miniconda3\envs\quantmaster\Scripts\reflex.exe run`

---

## 테스트

```bash
conda activate quantmaster
cd QuantMaster

# 단위 테스트 실행 (네트워크 불필요, 199건)
pytest tests/ --ignore=tests/test_data_loader.py -v

# 통합 테스트 실행 (실제 네트워크 필요)
pytest tests/test_data_loader.py -m integration -v
```

### 테스트 구성

| 파일 | 대상 | 건수 | 네트워크 |
|------|------|------|---------|
| `test_indicators.py` | VWAP 수식·MFI 범위·OBV 방향성 | 15 | ✗ |
| `test_backtester.py` | MDD·Sharpe·_simulate 로직 | 13 | ✗ |
| `test_scanner.py` | 완화 단계 구조·스캔 로직(mock) | 10 | ✗ |
| `test_psr.py` | 분기 PSR 계산 로직 | 5 | ✗ |
| `test_strategy_engine.py` | 분할 매수 플랜 계산 | 19 | ✗ |
| `test_breakout_filter.py` | 돌파 필터 로직 | 18 | ✗ |
| `test_accumulation_indicators.py` | 세력 매집 지표 계산 | 59 | ✗ |
| `test_scan_db.py` | 스캔 저장·히스토리·보유 종목 CRUD·포트폴리오 집계 | 60 | ✗ |
| `test_data_loader.py` | NAVER·FDR 실제 연결 | 9 | ✓ |

---

## 화면 구성

초기 진입 탭: **시장모멘텀**

```
QuantMaster Pro
├── [스캐너 탭 — 사이드바]
│   ├── 스캔 모드 선택
│   │   ├── 퀀트 스캔      (저PBR + GPA + VWAP 돌파 + MFI/OBV)
│   │   ├── 세력 탐지      (OBV 스파이크 + 돌파 + 알파 + 숏커버)
│   │   ├── 하락방어       (Beta + RS + Downside Capture, KR 전용)
│   │   └── 모멘텀 스캔    (기간별 수익률 상위 종목 — 삼성전기/LG이노텍 류)
│   ├── 시장 선택 (KOSPI / KOSDAQ / KR-ETF / S&P500 / NASDAQ / US-ETF)
│   ├── [퀀트 스캔 옵션]   PBR 슬라이더 · 시총 · VWAP 기간
│   ├── [세력 탐지 옵션]   알파 필터 · 공매도 필터 · 최대탐색시간
│   ├── [하락방어 옵션]    분석기간 · Beta 한도 · 최소시총
│   ├── [모멘텀 스캔 옵션] 기간(1주/1개월/3개월) · 최소시총
│   ├── 스캔 실행 버튼
│   └── 결과 저장 버튼
│
└── [메인 탭]
    ├── 시장모멘텀 탭 ← 기본 진입 탭
    │   ├── 추천 카드 4종 (단순모멘텀 / VAA / MA200 / 역변동성)
    │   ├── 자산별 수익률 테이블 (1M/3M/6M/12M · VAA점수 · MA200 · 변동성)
    │   └── 모멘텀 전략 백테스트 (기간 선택 → 수익률 추이)
    │
    ├── 섹터모멘텀 탭
    │   ├── KR / US 전환 버튼
    │   └── ETF 수익률 테이블 (5일/1개월/3개월/6개월/12개월, 1M 기준 정렬)
    │
    ├── 당일주도주 탭
    │   ├── 기간 선택: 오늘 / 1주 / 1개월 / 3개월
    │   │   ├── [오늘] NAVER/Yahoo 거래량·상승률 상위 + A/B점수 + 종가매매 후보
    │   │   └── [1주~3개월] 기간별 수익률 상위 종목 테이블 (기간모멘텀 TOP30)
    │   └── 연속 등장 추적 (오늘 모드)
    │
    ├── 스캐너 탭
    │   ├── [퀀트 모드] 결과 테이블
    │   │   └── 종목명 · 심볼 · 시가총액 · PBR · PSR · 배당률
    │   │       MFI · 현재가 · VWAP · 괴리율 · 조건 · [분석]
    │   ├── [세력 탐지 모드] 결과 테이블
    │   │   └── 종목명 · 시그널일 · 점수 · 시그널 타입 · 현재가 · 거래량비율 · [분석]
    │   ├── [하락방어 모드] 결과 테이블
    │   │   └── 종목명 · 시가총액 · Beta · RS · 하락포착률 · 하락일상승% · [분석]
    │   └── [모멘텀 스캔 모드] 결과 테이블
    │       └── 순위 · 종목명 · 수익률 · 1주수익률 · 거래량비 · 현재가 · 시가총액 · [조회]
    │
    ├── 분석 탭 (종목 선택 후)
    │   ├── 종목명 + 종가 기준일 + 보유 추가 버튼 + PDF 저장
    │   ├── 보유 추가 폼 (매수가 · 수량 · 메모 입력 → 등록)
    │   ├── [퀀트 모드]
    │   │   ├── 매수 근거
    │   │   ├── 분할 매수 플랜 (예산 입력 → 계산하기)
    │   │   ├── 지표 해석 가이드 (MFI / OBV)
    │   │   └── 매도 가이드
    │   ├── [세력 탐지 모드]
    │   │   └── 세력 매집 탐지 요약
    │   ├── 가격 차트 (공통) ─ 종가 + VWAP + TWAP20/60/120 + SMA120
    │   ├── [세력 탐지 모드] OBV 차트 + 공매도 잔고 추이
    │   ├── [퀀트 모드] 분기별 PSR 추이 (바 차트)
    │   ├── [퀀트 모드] 적용된 스캔 조건 패널
    │   ├── [퀀트 모드] 실제 측정값 패널
    │   └── 백테스트 실행 버튼
    │
    ├── 백테스트 탭
    │   ├── VWAP 돌파 전략 설명 (진입 · 청산 · 기본 설정)
    │   ├── 결과 지표 카드 (총수익률 · MDD · 승률 · 평균수익률 · 샤프지수 · 거래수)
    │   ├── 가격 차트 (매수/매도 마커 포함)
    │   ├── 자본금 추이 차트
    │   └── 매매 내역 테이블
    │
    ├── 히스토리 탭
    │   ├── 저장된 스캔 선택 (드롭다운)
    │   └── 결과 테이블
    │       ├── [퀀트] 종목명 · PBR · PSR · 배당률 · MFI · 현재가 · VWAP · 조건 · [분석]
    │       └── [세력 탐지] 종목명 · 시그널일 · 점수 · 시그널 · 현재가 · 거래량비율
    │
    ├── 보유종목 탭
    │   ├── 보유 종목 수 표시
    │   └── 보유 종목 테이블
    │       └── 종목명 · 시장 · 현재가 · VWAP · 괴리율 · MFI · PBR
    │           매수가 · 수량 · 메모 · 등록일 · [분석] [삭제]
    │
    └── 보유종목분석 탭
        ├── 포트폴리오 요약 카드 4종
        │   ├── 총 종목 수
        │   ├── 총 투자금
        │   ├── 예상 손익 (양수=초록 / 음수=빨강)
        │   └── 손익률 % (양수=초록 / 음수=빨강)
        └── 종목별 손익 테이블
            └── 종목명 · 시장 · 매수가 · 현재가 · 수량 · 투자금
                손익금액 · 손익률(%) · MFI · VWAP괴리율 · 메모 · [분석]
```
