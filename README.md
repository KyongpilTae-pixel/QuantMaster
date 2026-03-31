# QuantMaster Pro v2.0

**Hybrid Quant & Technical Breakout Scanner**

한국 주식(KOSPI/KOSDAQ)에서 퀀트 지표(PBR, ROE)와 기술적 지표(VWAP, MFI, OBV)를 결합해 매수 후보를 자동 발굴하는 스캐너. Reflex 기반 웹 UI로 스캔 결과, 투자 근거, 가격 차트, 백테스트 결과를 제공한다.

---

## 목차

- [아키텍처](#아키텍처)
- [스캔 로직](#스캔-로직)
- [파일별 설명](#파일별-설명)
- [설치 방법](#설치-방법)
- [실행 방법](#실행-방법)
- [화면 구성](#화면-구성)

---

## 아키텍처

```
[ NAVER Finance ]  ──PBR/ROE──►  data_loader.py
[ FinanceDataReader ] ─OHLCV──►  data_loader.py
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
                              ┌────────┴────────┐
                          [스캐너 탭]     [분석 탭]     [백테스트 탭]
```

**데이터 흐름**

1. NAVER Finance → PBR / ROE (시장 스냅샷, 최대 8페이지 × ~50종목)
2. FinanceDataReader → 개별 종목 OHLCV (최근 400거래일)
3. TechnicalIndicators → VWAP · MFI · OBV 계산
4. QuantScanner → 3단계 필터링 → 결과 10개 목표
5. Reflex State → 비동기 이벤트 핸들러로 UI 업데이트

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
│   ├── data_loader.py   # 시장 데이터 수집 (NAVER Finance + FinanceDataReader)
│   ├── indicators.py    # 기술적 지표 계산 (VWAP · TWAP · MFI · OBV)
│   └── reasoning.py     # 매수 근거 · 매도 가이드 텍스트 생성
├── scanner.py           # 3단계 하이브리드 스캔 + 자동 임계값 완화
├── backtester.py        # VWAP 돌파 전략 백테스트 (MDD · Sharpe · 승률)
├── rxconfig.py          # Reflex 설정 (app_name = "main")
├── requirements.txt     # Python 의존성
└── .gitignore
```

### `utils/data_loader.py`
- `QuantDataLoader.get_market_snapshot(market, max_pages)` — NAVER Finance 시가총액 페이지를 스크래핑해 PBR / ROE 데이터 반환. pykrx KRX API 연결 불가 문제로 NAVER 방식 사용.
- `QuantDataLoader.get_ohlcv(symbol, lookback_days)` — FinanceDataReader로 개별 종목 OHLCV 반환.

### `utils/indicators.py`
- `TechnicalIndicators.calculate_all(df, windows)` — VWAP · TWAP (복수 기간) · MFI(14일) · OBV · OBV_Signal(20일 MA) 계산.

### `utils/reasoning.py`
- `InvestmentReasoning.generate_report(name, pbr, vwap_p, mfi, vwap_price)` — 매수 근거 / 매도 가이드 문자열 생성.

### `scanner.py`
- `QuantScanner.run_advanced_scan(target_pbr, vwap_period, min_count, market)` — 3단계 필터 + 5단계 자동 완화 스캔. 결과 DataFrame에 `Applied_PBR / Applied_GPA / Applied_MFI / Applied_OBV / Condition` 포함.

### `backtester.py`
- `Backtester.run(symbol, name, vwap_period, initial_capital)` — VWAP 돌파 진입 / VWAP 이탈 청산 전략 시뮬레이션. 총수익률 · MDD · 승률 · 평균수익 · Sharpe · 자본금 추이 · 매매 내역 반환.

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
| `finance-datareader` | OHLCV 데이터 수집 |
| `pykrx` | (설치 유지, 향후 KRX API 복구 대비) |
| `plotly` | 차트 렌더링 |
| `reflex` | 웹 UI 프레임워크 |
| `requests` / `beautifulsoup4` / `lxml` | NAVER Finance 스크래핑 |

---

## 실행 방법

```bash
# conda 환경 활성화 후
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

## 화면 구성

### 스캐너 탭
- 시장 / PBR 한도 / VWAP 기간 설정 후 **스캔 실행**
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
