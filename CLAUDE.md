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
│   └── strategy_engine.py   # 3단계 분할 매수 플랜 계산
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
    └── test_data_loader.py  # @integration 마크 (네트워크 필요)
```

---

## 핵심 설계 결정

### 데이터 수집
- **한국 시장**: pykrx/KRX API 연결 불가로 NAVER Finance 스크래핑으로 대체
  - `field_submit` POST로 `market_sum, sales, per, roe, pbr` 필드 선택
  - 컬럼 순서: `[6]=시가총액(억원) [7]=매출액(억원) [8]=PER [9]=ROE [10]=PBR`
  - PSR = 시가총액 / 매출액
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
- **프로세스 종료**: `cmd //c "taskkill /f /im python.exe & taskkill /f /im node.exe"`

---

## 분석 탭 구성 순서

1. 매수 근거
2. **분할 매수 플랜** (예산 입력 → 계산하기)
3. MFI/OBV 지표 설명
4. 매도 가이드
5. 가격 차트 (종가 + VWAP + TWAP20 + TWAP60)
6. 분기별 PSR 추이 (바 차트)
7. 적용된 스캔 조건
8. 실제 측정값

---

## 테스트

```bash
# 단위 테스트 (네트워크 불필요, 69건)
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
| 포트 충돌 (3000/8000) | `taskkill /f /im python.exe & node.exe` |
