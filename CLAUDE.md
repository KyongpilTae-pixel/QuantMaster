# QuantMaster Pro v2.0 — Claude 작업 컨텍스트

## 프로젝트 개요
한국(KOSPI/KOSDAQ) 및 미국(S&P500/NASDAQ) 주식의 퀀트+기술적 하이브리드 스캐너.
Reflex 프레임워크 기반 웹 UI. Python 3.11, conda 환경명 `quantmaster`.

**GitHub**: https://github.com/KyongpilTae-pixel/QuantMaster.git
**실행**: `conda activate quantmaster` → `reflex run` → http://localhost:3000

---

## 프로젝트 구조

```
QuantMaster/
├── main/
│   ├── __init__.py
│   └── main.py              # Reflex UI (State, 컴포넌트, 이벤트 핸들러)
├── utils/
│   ├── __init__.py
│   ├── data_loader.py       # NAVER Finance(KR) + yfinance(US) 데이터 수집
│   ├── indicators.py        # VWAP, TWAP, MFI, OBV 계산
│   ├── reasoning.py         # 매수근거/매도가이드 텍스트 생성
│   ├── strategy_engine.py   # 3단계 분할 매수 플랜 계산
│   └── scan_db.py           # SQLite CRUD (스캔·히스토리·보유종목)
├── scanner.py               # 3단계 하이브리드 스캔 + 자동 임계값 완화
├── backtester.py            # VWAP 돌파 전략 백테스트
├── rxconfig.py              # Reflex 설정 (app_name="main")
├── requirements.txt
└── tests/
    ├── conftest.py
    ├── test_indicators.py
    ├── test_backtester.py
    ├── test_scanner.py
    ├── test_psr.py
    ├── test_strategy_engine.py
    ├── test_breakout_filter.py
    ├── test_accumulation_indicators.py
    ├── test_scan_db.py       # 보유종목 CRUD + 포트폴리오 집계 로직 (60건)
    └── test_data_loader.py   # @integration 마크 (네트워크 필요)
```

---

## 핵심 설계 결정

### 데이터 수집
- **한국 시장**: pykrx/KRX API 연결 불가로 NAVER Finance 스크래핑으로 대체
  - `field_submit` POST로 `market_sum, sales, dividend, per, roe, pbr` 필드 선택
  - 컬럼 순서: `[6]=시가총액(억원) [7]=매출액(억원) [8]=주당배당금(원) [9]=PER [10]=ROE [11]=PBR`
  - PSR = 시가총액 / 매출액; `len < 12` 체크
  - 배당수익률(%) = 주당배당금(원) / 현재가 × 100 (NAVER dividend 필드는 원/주 단위)
- **미국 시장**: FinanceDataReader로 구성종목 목록 → yfinance 병렬 수집 (ThreadPoolExecutor)
- **OHLCV**: FinanceDataReader (한국/미국 공통)

### 스캔 로직 (scanner.py)
3단계 필터: Quant(PBR+GPA) → Technical(VWAP 돌파) → Momentum(MFI+OBV)

5단계 자동 완화 (`_RELAXATION_STEPS`):
```python
(1, 1.2, 0.6, 50, True)   # 원본
(2, 1.5, 0.4, 45, True)   # PBR완화
(3, 2.0, 0.2, 45, True)   # GPA완화
(4, 2.0, 0.0, 45, False)  # OBV제외
(5, 2.0, 0.0, 40, False)  # MFI완화
```

시가총액 프리셋 (`_CAP_PRESETS`): 전체/소형주+(KR:300억/US:$2B)/중형주+/대형주+

### 기술 지표 (indicators.py)
- MFI 엣지케이스: 순수 상승 추세 → MFI=100, 횡보 → MFI=50 (neg_mf=0 처리)
- `np.errstate(divide="ignore", invalid="ignore")` 로 경고 억제

### 분할 매수 플랜 (strategy_engine.py)
- 기본 3분할: 현재가 30% / 중간가 30% / VWAP 40%
- MFI ≥ 80 (과열): 방어적 3분할 10% / 30% / 60%
- 현재가-VWAP 차이 ≤ 2% (밀착): 2분할 50% / 50%
- 손절선: VWAP × 0.96

### 분기별 PSR 추이
- yfinance `quarterly_financials["Total Revenue"]` + `history().resample("QE")`
- 한국: 종목코드 + `.KS` (KOSPI) 또는 `.KQ` (KOSDAQ) 접미사

---

## Reflex 관련 주의사항

- **앱 구조**: `main/main.py` 패키지 구조 필수 (`rxconfig.py`에 `app_name="main"`)
- **슬라이더**: `value=State.pbr_limit` 형태로 `List[float]` 상태 변수 필요
  - `value=[State.float_var]` 형태(Python 리스트로 감싸기)는 반응형 작동 안 함
- **State setter**: Reflex 0.8+에서 명시적 setter 메서드 필요
- **recharts reference_line label**: dict 불가, 문자열만 허용
- **rx.radio_group / rx.tabs.root / rx.select value 바인딩 루프**: `value=State.var` + `on_change` 조합 시 Reflex가 상태를 프론트엔드로 보낼 때마다 `on_change`가 재발화 → 무한루프 또는 콘텐츠 사라짐 (Reflex 0.8.x, Radix SelectRoot 계열 전체 해당). 해결: `on_change` 제거 + 각 트리거에 `on_click=State.set_xxx("yyy")` 개별 추가. `rx.radio_group` · `rx.select`는 `rx.button` 배열로 대체. setter에 `if v == self.xxx: return` 가드도 함께 추가할 것
- **List[dict] in-place 변경 루프**: `sorted_data`가 `leaders_data_raw`와 dict 객체를 공유할 때 `item["rank"]=i+1` 직접 변경 → Reflex가 raw도 변경됐다고 감지 → 루프. `{**item, "rank": i+1}` 새 dict 생성으로 해결
- **프로세스 종료**: `cmd //c "taskkill /f /im python.exe & taskkill /f /im node.exe"`

---

## 탭 구성

### 분석 탭 순서
1. 종목 헤더 (이름 + 종가 기준일 + `+ 보유 추가` / `PDF 저장`)
2. 보유 정보 바 (보유중 뱃지 + 매수가/수량/메모) — 보유 종목 분석 시에만 표시
3. 보유 추가 폼 (display toggle, rx.cond 미사용)
4. 매수 근거 / **분할 매수 플랜** / 지표 가이드 / 매도 가이드 (퀀트 모드)
5. 가격 차트 (종가 + VWAP + TWAP20/60/120 + SMA120)
6. 분기별 PSR 추이 (바 차트, 퀀트 모드)
7. 적용된 스캔 조건 + 실제 측정값 (퀀트 모드)
8. 백테스트 실행 버튼

### 스캔 모드 (scan_mode 값)
| value | 모드명 | 설명 |
|-------|--------|------|
| quant | 퀀트 스캔 | PBR+GPA+VWAP+MFI+OBV 필터 |
| whale | 세력 탐지 | OBV스파이크+돌파+알파+숏커버 |
| defensive | 하락방어 | Beta+RS+Downside Capture (KOSPI/KOSDAQ 전용) |

### 하락방어 스캔 (defensive mode)
- `utils/defensive_scanner.py`: `scan_defensive_stocks(market, period_days, max_beta, min_mktcap_eok, top_n)`
- 지표: Beta(Cov/Var), RS(누적수익률 비율), Downside Capture(하락일 평균수익 비율), Up-on-Down(하락일 중 상승한 날 %)
- 시가총액 필터: 기본 1조(10,000억). Marcap은 원 단위 → `min_mktcap_eok × 1e8`로 비교
- 정렬: RS 내림차순 → Beta 오름차순 → DC 오름차순
- bool 플래그: `rs_positive`(RS>1.0), `dc_good`(DC<80%) — rx.foreach 안전용
- State: `defensive_results(List[dict])`, `defensive_period(int)`, `defensive_max_beta(List[float])`, `defensive_min_mktcap(int)`

### 메인 탭 목록
| value | 탭명 | 설명 |
|-------|------|------|
| scanner | 스캐너 | 스캔 결과 테이블 (퀀트/세력/하락방어) |
| analysis | 분석 | 선택 종목 상세 분석 |
| backtest | 백테스트 | VWAP 전략 시뮬레이션 결과 |
| history | 히스토리 | 저장된 스캔 기록 조회 |
| holdings | 보유종목 | 보유 종목 목록 · 삭제 |
| portfolio | 보유종목분석 | 포트폴리오 손익 집계 + 종목별 손익 |

### 보유종목분석 탭 (portfolio)
- 집계 카드 4개: 총 종목 수 / 총 투자금 / 예상 손익 / 손익률
- 종목별 테이블: 매수가·현재가·수량·투자금·손익금액·손익률%·MFI·VWAP괴리율·메모·[분석]
- 매수가/수량 미입력 시 손익 칸 `-` 표시
- State.holdings_analysis: List[dict] — 각 항목에 `has_buy`, `pnl_positive`, `pct_positive`, `is_us` 등 **미리 계산된 bool 플래그** 포함 (rx.foreach 내에서 ObjectItemOperation 비교 불가 문제 우회)

---

## 테스트

```bash
# 단위 테스트 (네트워크 불필요, 199건)
pytest tests/ --ignore=tests/test_data_loader.py -v

# 통합 테스트 (실제 네트워크 필요)
pytest tests/test_data_loader.py -m integration -v
```

---

## 알려진 이슈 / 해결된 문제

| 문제 | 해결책 |
|------|--------|
| pykrx KRX API 빈 응답 | NAVER Finance 스크래핑으로 완전 대체 |
| NAVER 시가총액 컬럼 누락 | `field_submit`에 `market_sum` 필드 추가 |
| MFI 순수 상승 추세에서 NaN | `neg_mf=0`일 때 MFI=100으로 처리 |
| Reflex 슬라이더 반응 없음 | `float` → `List[float]` 상태 변수로 변경 |
| recharts reference_line label TypeError | dict → str로 변경 |
| 포트 충돌 (3000/8000) | PowerShell WMI `Terminate()` + `--backend-port 7500` |
| rx.cond(False) 내 버튼 이벤트 미등록 | `display=rx.cond(...)` CSS 토글로 대체 |
| rx.foreach 내 dict var 비교 (`> 0`) TypeError | List[dict]에 bool 플래그 미리 계산 후 저장 |
| add_to_holdings 버튼 무반응 | selected_* 14개 필드에 선택 시점 메타 저장 방식으로 전환 |
| rx.select value+on_change 무한루프 (당일주도주) | `rx.select` → `rx.button` 배열 교체 + setter에 동일값 가드 |
