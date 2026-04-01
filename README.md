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
│   └── reasoning.py     # 매수 근거 · 매도 가이드 텍스트 생성 (KRW/USD 지원)
├── scanner.py           # 3단계 하이브리드 스캔 + 자동 임계값 완화
├── backtester.py        # VWAP 돌파 전략 백테스트 (MDD · Sharpe · 승률)
├── rxconfig.py          # Reflex 설정 (app_name = "main")
├── requirements.txt     # Python 의존성
├── tests/
│   ├── conftest.py      # pytest fixtures (ohlcv_uptrend · downtrend · flat)
│   ├── test_indicators.py   # TechnicalIndicators 단위 테스트 (15건)
│   ├── test_backtester.py   # Backtester 단위 테스트 (13건)
│   ├── test_scanner.py      # QuantScanner 단위 테스트 mock (10건)
│   └── test_data_loader.py  # 통합 테스트 (실제 네트워크, @integration 마크)
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

### `main/main.py`
- `State` — Reflex 앱 상태 (스캔 결과 · 선택 종목 · 차트 데이터 · 백테스트 요약).
- `run_scan()` — 비동기 스캔 실행, 진행 상태 실시간 업데이트.
- `select_stock()` — 종목 선택 시 투자 근거 생성 + 가격 차트 데이터 비동기 로드.
- `run_backtest()` — 선택 종목 백테스트 비동기 실행.

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

# 단위 테스트 실행 (네트워크 불필요, 38건)
pytest tests/test_indicators.py tests/test_backtester.py tests/test_scanner.py -v

# 통합 테스트 실행 (실제 네트워크 필요)
pytest tests/test_data_loader.py -m integration -v
```

### 테스트 구성

| 파일 | 대상 | 건수 | 네트워크 |
|------|------|------|---------|
| `test_indicators.py` | VWAP 수식·MFI 범위·OBV 방향성 | 15 | ✗ |
| `test_backtester.py` | MDD·Sharpe·_simulate 로직 | 13 | ✗ |
| `test_scanner.py` | 완화 단계 구조·스캔 로직(mock) | 10 | ✗ |
| `test_data_loader.py` | NAVER·FDR 실제 연결 | 9 | ✓ |

---

## 화면 구성

### 사이드바
- 시장 선택: **KOSPI / KOSDAQ / S&P 500 / NASDAQ**
- PBR 한도 슬라이더
- VWAP 기간 선택 (20 / 60 / 120일)
- 스캔 실행 버튼

### 스캐너 탭
- 결과 테이블: 종목명 · PBR · MFI · 현재가 · VWAP · 괴리율 · 적용 조건

### 분석 탭 (종목 선택 후)
1. **매수 근거** — VWAP 돌파·수급 기반 자동 생성
2. **매도 가이드** — VWAP 이탈 기준 손절 가이드
3. **가격 차트** — 종가(파란선) + VWAP(주황 점선)
4. **적용된 스캔 조건** — 어느 완화 단계가 적용됐는지 표시
5. **실제 측정값** — PBR · MFI · VWAP 괴리율 · OBV 충족 여부

### 백테스트 탭 (백테스트 실행 후)
- 총수익률 · MDD · 승률 · 평균수익률 · 샤프 지수 · 거래 수
- 자본금 추이 차트
- 매매 내역 테이블 (진입일 · 청산일 · 수익률 · 손익)
