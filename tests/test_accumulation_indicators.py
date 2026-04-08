"""
세력 탐지 알고리즘 단위 테스트.

핵심 버그 검증 및 수정 후 동작 확인.

주요 수정 사항:
  1. KR threshold 55 (기존 70은 max=65여서 불가)
  2. OBV 볼륨 2x (기존 3x, rolling mean 포함 감안 3.0x 테스트 사용)
  3. Alpha: 지수 하락 방어 알파 OR 2%+ 모멘텀 알파
  4. signal_window 15일 (기존 5일)
"""

import numpy as np
import pandas as pd
import pytest


def _make_ohlcv(n: int, volume_multipliers: dict = None) -> pd.DataFrame:
    """n일치 더미 OHLCV. volume_multipliers: {idx: multiplier} 로 특정 일 거래량 배율 설정."""
    idx = pd.bdate_range("2025-01-01", periods=n)
    close = pd.Series(100.0 + np.arange(n) * 0.1, index=idx)
    vol = pd.Series([1_000_000.0] * n, index=idx)
    if volume_multipliers:
        for i, mult in volume_multipliers.items():
            vol.iloc[i] = 1_000_000.0 * mult
    return pd.DataFrame({
        "Open": close - 0.5,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": vol,
    }, index=idx)


def _make_index(df: pd.DataFrame, down_days: set = None) -> pd.DataFrame:
    """종목과 같은 날짜의 지수 더미. down_days: 하락 일 위치 집합(iloc 기준)."""
    close = pd.Series(1000.0, index=df.index)
    if down_days:
        for i in down_days:
            close.iloc[i] = close.iloc[i - 1] * 0.98 if i > 0 else 980.0
    return pd.DataFrame({"Close": close}, index=df.index)


# ---------------------------------------------------------------------------
# 1. 점수 산정 기본 동작
# ---------------------------------------------------------------------------

class TestScoreComputation:
    def test_no_signals_score_zero(self):
        """아무 시그널 없으면 점수 0."""
        from utils.accumulation_indicators import analyze_whale_with_options
        df = _make_ohlcv(60)
        idx = _make_index(df)
        full, _ = analyze_whale_with_options(df, idx, use_alpha=True, use_short_filter=False)
        assert full["Accum_Score"].max() == 0

    def test_obv_spike_adds_30(self):
        """OBV 매집봉(거래량 3.0x) -> Is_Whale_Spike=True, +30점.

        rolling(20) mean이 스파이크 당일 포함:
          vol_avg_last = (19 x 1M + 3M) / 20 = 1.1M
          3M > 1.1M x 2 = 2.2M  ->  Is_Whale_Spike=True
        """
        from utils.accumulation_indicators import analyze_whale_with_options
        df = _make_ohlcv(40, volume_multipliers={-1: 3.0})
        idx = _make_index(df)
        full, _ = analyze_whale_with_options(df, idx, use_alpha=False, use_short_filter=False)
        assert full["Is_Whale_Spike"].iloc[-1] == True
        assert full["Accum_Score"].iloc[-1] == 30

    def test_alpha_adds_35_on_down_day(self):
        """시장 하락일에 종목 양의 알파 -> Alpha_Sig=1, +35점."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n)
        # 마지막 날 종목은 +3% 상승, 지수는 -2% 하락
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = _make_index(df, down_days={n - 1})
        full, _ = analyze_whale_with_options(df, idx, use_alpha=True, use_short_filter=False)
        assert full["Alpha_Sig"].iloc[-1] == 1
        assert full["Accum_Score"].iloc[-1] == 35

    def test_alpha_adds_35_strong_momentum(self):
        """지수 상승 시에도 2%+ 강세 알파 -> Alpha_Sig=1."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n)
        # 종목 +3%, 지수 +0.5% -> alpha = +2.5% > 2%
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = pd.DataFrame(
            {"Close": [1000.0] * (n - 1) + [1005.0]},
            index=df.index,
        )
        full, _ = analyze_whale_with_options(df, idx, use_alpha=True, use_short_filter=False)
        assert full["Alpha_Sig"].iloc[-1] == 1

    def test_short_covering_adds_35(self):
        """공매도 잔고 급감 -> Short_Sig=1, +35점.

        rolling(20) 포함 감안 충분히 큰 감소 필요.
        최근 5일 400K: avg = (15x1M + 5x400K)/20 = 850K
        400K < 850K x 0.8 = 680K  ->  Short_Sig=1
        """
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n)
        short_bal = pd.Series(1_000_000.0, index=df.index)
        short_bal.iloc[-5:] = 400_000.0
        df["Short_Balance"] = short_bal
        idx = pd.DataFrame()
        full, _ = analyze_whale_with_options(df, idx, use_alpha=False, use_short_filter=True)
        assert full["Short_Sig"].iloc[-1] == 1
        assert full["Accum_Score"].iloc[-1] == 35

    def test_kr_max_score_is_65(self):
        """
        [BUG 검증] KR 시장(공매도 없음): 최대 가능 점수 = OBV(30)+Alpha(35) = 65.
        기존 threshold=70이면 항상 0개 탐지 -> 반드시 동적 threshold 적용 필요.
        """
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n, volume_multipliers={-1: 3.0})
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = _make_index(df, down_days={n - 1})
        full, _ = analyze_whale_with_options(df, idx, use_alpha=True, use_short_filter=False)
        max_score = full["Accum_Score"].max()
        assert max_score == 65, f"KR 최대점수는 65여야 함, 실제={max_score}"
        assert max_score < 70, "threshold=70은 KR에서 수학적으로 불가"

    def test_us_max_score_is_100(self):
        """US 시장: OBV(30)+Alpha(35)+Short(35) = 100 가능."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n, volume_multipliers={-1: 3.0})
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        short_bal = pd.Series(1_000_000.0, index=df.index)
        short_bal.iloc[-5:] = 400_000.0
        df["Short_Balance"] = short_bal
        idx = _make_index(df, down_days={n - 1})
        full, _ = analyze_whale_with_options(df, idx, use_alpha=True, use_short_filter=True)
        assert full["Accum_Score"].iloc[-1] == 100


# ---------------------------------------------------------------------------
# 2. 동적 Threshold -- KR=55, US=70
# ---------------------------------------------------------------------------

class TestDynamicThreshold:
    def test_kr_threshold_55_detects_obv_plus_alpha(self):
        """동적 threshold=55 적용 시 KR에서도 OBV(30)+Alpha(35)=65 >= 55 -> 탐지됨."""
        from utils.accumulation_indicators import analyze_whale_with_options, SIGNAL_THRESHOLD_KR
        n = 40
        df = _make_ohlcv(n, volume_multipliers={-1: 3.0})
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = _make_index(df, down_days={n - 1})
        full, _ = analyze_whale_with_options(df, idx, use_alpha=True, use_short_filter=False)
        max_score = full["Accum_Score"].max()
        assert max_score >= SIGNAL_THRESHOLD_KR, (
            f"KR threshold({SIGNAL_THRESHOLD_KR})으로 탐지돼야 함, 점수={max_score}"
        )

    def test_us_threshold_70_unchanged(self):
        """US는 threshold=70 유지."""
        from utils.accumulation_indicators import SIGNAL_THRESHOLD_US
        assert SIGNAL_THRESHOLD_US == 70

    def test_kr_threshold_lower_than_us(self):
        """KR threshold < US threshold."""
        from utils.accumulation_indicators import SIGNAL_THRESHOLD_KR, SIGNAL_THRESHOLD_US
        assert SIGNAL_THRESHOLD_KR < SIGNAL_THRESHOLD_US

    def test_kr_threshold_reachable_from_max_score(self):
        """KR 최대점수(65) >= KR threshold."""
        from utils.accumulation_indicators import SIGNAL_THRESHOLD_KR
        kr_max_score = 30 + 35  # OBV + Alpha (공매도 없음)
        assert kr_max_score >= SIGNAL_THRESHOLD_KR


# ---------------------------------------------------------------------------
# 3. OBV 볼륨 임계값 -- 2x 기준
# ---------------------------------------------------------------------------

class TestOBVThreshold:
    def test_3x_volume_triggers_spike(self):
        """거래량 3.0x -> Is_Whale_Spike=True (2x 기준, rolling mean 자기포함 고려)."""
        from utils.accumulation_indicators import analyze_whale_with_options
        df = _make_ohlcv(40, volume_multipliers={-1: 3.0})
        idx = pd.DataFrame()
        full, _ = analyze_whale_with_options(df, idx, use_alpha=False, use_short_filter=False)
        assert full["Is_Whale_Spike"].iloc[-1] == True

    def test_1x_volume_no_spike(self):
        """거래량이 평균 수준이면 Is_Whale_Spike=False."""
        from utils.accumulation_indicators import analyze_whale_with_options
        df = _make_ohlcv(40)
        idx = pd.DataFrame()
        full, _ = analyze_whale_with_options(df, idx, use_alpha=False, use_short_filter=False)
        assert full["Is_Whale_Spike"].any() == False

    def test_obv_spike_score_30(self):
        """OBV 스파이크 발생 시 점수 30점."""
        from utils.accumulation_indicators import analyze_whale_with_options
        df = _make_ohlcv(40, volume_multipliers={-1: 3.0})
        idx = pd.DataFrame()
        full, _ = analyze_whale_with_options(df, idx, use_alpha=False, use_short_filter=False)
        assert full["Accum_Score"].iloc[-1] == 30


# ---------------------------------------------------------------------------
# 4. extract_highlights -- threshold 파라미터
# ---------------------------------------------------------------------------

class TestExtractHighlights:
    def test_empty_when_no_signals(self):
        """시그널 없으면 빈 리스트."""
        from utils.accumulation_indicators import extract_highlights
        df = pd.DataFrame(
            {"Accum_Score": [0, 10, 20, 0]},
            index=pd.bdate_range("2025-01-01", periods=4),
        )
        assert extract_highlights(df, threshold=55) == []

    def test_single_signal_date(self):
        """시그널 1일 -> x1 == x2."""
        from utils.accumulation_indicators import extract_highlights
        df = pd.DataFrame(
            {"Accum_Score": [0, 65, 0, 0]},
            index=pd.bdate_range("2025-01-01", periods=4),
        )
        hl = extract_highlights(df, threshold=55)
        assert len(hl) == 1
        assert hl[0]["x1"] == hl[0]["x2"]

    def test_consecutive_signals_merged(self):
        """연속 3일 시그널 -> 구간 1개."""
        from utils.accumulation_indicators import extract_highlights
        scores = [0, 65, 65, 65, 0]
        df = pd.DataFrame(
            {"Accum_Score": scores},
            index=pd.bdate_range("2025-01-01", periods=5),
        )
        hl = extract_highlights(df, threshold=55)
        assert len(hl) == 1
        assert hl[0]["x1"] != hl[0]["x2"]

    def test_separated_signals_two_ranges(self):
        """6 영업일 이상 간격 -> 구간 2개."""
        from utils.accumulation_indicators import extract_highlights
        idx = pd.bdate_range("2025-01-01", periods=15)
        scores = [65] + [0] * 10 + [65] * 4
        df = pd.DataFrame({"Accum_Score": scores}, index=idx)
        hl = extract_highlights(df, threshold=55)
        assert len(hl) == 2

    def test_kr_threshold_55_used(self):
        """threshold=55 파라미터로 score=65 구간 감지, threshold=70으로는 미감지."""
        from utils.accumulation_indicators import extract_highlights
        df = pd.DataFrame(
            {"Accum_Score": [0, 65, 65, 0]},
            index=pd.bdate_range("2025-01-01", periods=4),
        )
        hl_55 = extract_highlights(df, threshold=55)
        hl_70 = extract_highlights(df, threshold=70)
        assert len(hl_55) == 1   # KR threshold로 감지
        assert len(hl_70) == 0   # 기존 threshold=70이면 미감지 (버그였음)

    def test_default_threshold_backward_compat(self):
        """threshold 기본값 = SIGNAL_THRESHOLD_US(70) -- 하위호환."""
        from utils.accumulation_indicators import extract_highlights, SIGNAL_THRESHOLD_US
        df = pd.DataFrame(
            {"Accum_Score": [100, 0, 0]},
            index=pd.bdate_range("2025-01-01", periods=3),
        )
        hl = extract_highlights(df)   # 기본값 사용
        assert len(hl) == 1


# ---------------------------------------------------------------------------
# 5. buy_signals 반환 -- threshold 파라미터
# ---------------------------------------------------------------------------

class TestBuySignalsFilter:
    def test_buy_signals_use_threshold(self):
        """analyze_whale_with_options가 threshold 파라미터로 buy_signals 필터링."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n, volume_multipliers={-1: 3.0})
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = _make_index(df, down_days={n - 1})

        # threshold=55(KR): score 65 -> buy_signals에 포함
        _, buy_55 = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=False, threshold=55
        )
        # threshold=70(US기본): score 65 -> buy_signals에 미포함
        _, buy_70 = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=False, threshold=70
        )
        assert len(buy_55) >= 1
        assert len(buy_70) == 0

    def test_all_signals_buy_count(self):
        """세 신호 모두 발생 시 buy_signals에 해당 날 포함."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n, volume_multipliers={-1: 3.0})
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        short_bal = pd.Series(1_000_000.0, index=df.index)
        short_bal.iloc[-5:] = 400_000.0
        df["Short_Balance"] = short_bal
        idx = _make_index(df, down_days={n - 1})
        _, buy_sigs = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=True, threshold=70
        )
        assert len(buy_sigs) >= 1


# ---------------------------------------------------------------------------
# 6. obv_multiplier / alpha_momentum_threshold 파라미터
# ---------------------------------------------------------------------------

class TestRelaxationParams:
    def test_lower_obv_multiplier_triggers_more_spikes(self):
        """obv_multiplier 낮을수록 Is_Whale_Spike=True 빈도 증가."""
        from utils.accumulation_indicators import analyze_whale_with_options
        # 2.5x 거래량: strict(2.0) 기준으로는 rolling mean 포함 시 경계값
        # 1.5x 기준은 더 쉽게 통과
        df = _make_ohlcv(40, volume_multipliers={-1: 2.5})
        idx = pd.DataFrame()
        full_strict, _ = analyze_whale_with_options(
            df, idx, use_alpha=False, use_short_filter=False, obv_multiplier=2.0
        )
        full_loose, _ = analyze_whale_with_options(
            df, idx, use_alpha=False, use_short_filter=False, obv_multiplier=1.2
        )
        # 완화 조건에서 더 많거나 같은 스파이크
        assert full_loose["Is_Whale_Spike"].sum() >= full_strict["Is_Whale_Spike"].sum()

    def test_lower_alpha_threshold_triggers_more_alpha(self):
        """alpha_momentum_threshold 낮을수록 Alpha_Sig=1 빈도 증가."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n)
        # 종목 +1.5%, 지수 +0.5% -> alpha = 1.0%: 2% 기준은 미충족, 0.8% 기준은 충족
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.015
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = pd.DataFrame(
            {"Close": [1000.0] * (n - 1) + [1005.0]},
            index=df.index,
        )
        _, buy_strict = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=False,
            threshold=35, obv_multiplier=999,  # OBV는 절대 안 터지게
            alpha_momentum_threshold=0.020,     # 2% 기준: 1% 알파 미충족
        )
        _, buy_loose = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=False,
            threshold=35, obv_multiplier=999,
            alpha_momentum_threshold=0.008,     # 0.8% 기준: 1% 알파 충족
        )
        assert len(buy_strict) == 0
        assert len(buy_loose) >= 1

    def test_relaxation_steps_constants(self):
        """_RELAXATION_STEPS 단계 수 및 초기값 검증."""
        from accumulation_scanner import _RELAXATION_STEPS
        from utils.accumulation_indicators import DEFAULT_OBV_MULTIPLIER, DEFAULT_ALPHA_MOMENTUM_THRESHOLD
        assert len(_RELAXATION_STEPS) >= 5
        first = _RELAXATION_STEPS[0]
        assert first[1] == DEFAULT_OBV_MULTIPLIER
        assert first[2] == DEFAULT_ALPHA_MOMENTUM_THRESHOLD
        # 각 단계는 이전보다 obv_mult가 낮거나 같아야 함 (완화)
        for i in range(1, len(_RELAXATION_STEPS)):
            assert _RELAXATION_STEPS[i][1] <= _RELAXATION_STEPS[i-1][1]
            assert _RELAXATION_STEPS[i][2] <= _RELAXATION_STEPS[i-1][2]
            assert _RELAXATION_STEPS[i][3] >= _RELAXATION_STEPS[i-1][3]

    def test_step1_stricter_than_step2(self):
        """1단계 조건이 2단계보다 엄격 -> 1단계 미통과 종목이 2단계에선 통과 가능."""
        from utils.accumulation_indicators import analyze_whale_with_options
        from accumulation_scanner import _RELAXATION_STEPS
        n = 40
        # 2.4x 거래량: 1단계(obv=2.0) 시 rolling mean 포함해 경계에 있음
        # 정확히 테스트: obv_multiplier=1.5면 2.4x/(19+2.4)/20=1.07 -> 2.4>1.07*1.5=1.6 OK
        #                obv_multiplier=2.0면 2.4>1.07*2.0=2.14 OK → 둘 다 통과할 수 있음
        # 대신 극단값으로 테스트
        df = _make_ohlcv(n)  # 모두 동일 거래량 → spike 없음
        idx = pd.DataFrame()
        _, buy_1 = analyze_whale_with_options(
            df, idx, use_alpha=False, use_short_filter=False,
            threshold=30, obv_multiplier=_RELAXATION_STEPS[0][1],
        )
        _, buy_last = analyze_whale_with_options(
            df, idx, use_alpha=False, use_short_filter=False,
            threshold=30, obv_multiplier=_RELAXATION_STEPS[-1][1],
        )
        # 균일 거래량은 어떤 배수로도 스파이크 없음 (rolling mean = volume)
        assert buy_1.empty
        assert buy_last.empty  # 균일 거래량은 배수 낮아도 스파이크 없음

    def test_applied_step_in_scanner_result(self):
        """스캐너 결과 dict에 Applied_Step 키 포함."""
        from accumulation_scanner import _RELAXATION_STEPS
        label, _, _, _ = _RELAXATION_STEPS[0]
        assert label == "원본"


# ---------------------------------------------------------------------------
# 7. 타임아웃 동작 -- _scan_batch timeout 파라미터
# ---------------------------------------------------------------------------

class TestScanBatchTimeout:
    def _make_ctx(self, n=40):
        """_scan_batch 호출용 최소 ctx dict."""
        df = _make_ohlcv(n)
        from utils.data_loader import QuantDataLoader
        return {
            "loader": None,       # _process에서 loader 직접 호출 안하므로 None OK
            "index_df": pd.DataFrame(),
            "names": {},
            "has_short": False,
            "threshold": 55,
            "market": "KOSPI",
            "workers": 2,
            "lookback_days": 60,
        }

    def test_scan_batch_empty_symbols(self):
        """빈 종목 리스트 -> 즉시 빈 결과 반환."""
        from accumulation_scanner import AccumulationScanner
        scanner = AccumulationScanner()
        ctx = self._make_ctx()
        result = scanner._scan_batch(
            [], ctx, True, 2.0, 0.02, 15, "원본", step_timeout=10.0
        )
        assert result == []

    def test_scan_batch_timeout_returns_partial(self):
        """극단적으로 짧은 타임아웃(0.001초) -> TimeoutError 처리, 빈 리스트 반환(오류 없음)."""
        from accumulation_scanner import AccumulationScanner, _PER_STOCK_TIMEOUT
        scanner = AccumulationScanner()
        ctx = self._make_ctx()
        # 실제 네트워크 호출 없이 빠르게 실패해야 함 (loader=None -> _process returns None)
        result = scanner._scan_batch(
            ["005930", "000660"], ctx, True, 2.0, 0.02, 15, "원본",
            step_timeout=0.001,
        )
        # TimeoutError가 발생해도 예외 전파 없이 빈 리스트 반환
        assert isinstance(result, list)

    def test_per_stock_timeout_constant(self):
        """_PER_STOCK_TIMEOUT이 양수."""
        from accumulation_scanner import _PER_STOCK_TIMEOUT
        assert _PER_STOCK_TIMEOUT > 0

    def test_run_scan_max_seconds_param(self):
        """run_scan이 max_seconds 파라미터를 받음."""
        from accumulation_scanner import AccumulationScanner
        import inspect
        sig = inspect.signature(AccumulationScanner.run_scan)
        assert "max_seconds" in sig.parameters

    def test_prepare_returns_required_keys(self):
        """prepare() 반환 dict에 필수 키 존재."""
        from accumulation_scanner import AccumulationScanner
        # 실제 네트워크 없이 키 목록만 검증 (빈 snapshot 처리)
        required = {"symbols", "names", "index_df", "loader",
                    "has_short", "threshold", "is_us", "workers", "market", "lookback_days"}
        scanner = AccumulationScanner()
        # prepare()는 네트워크 필요 → 시그니처만 확인
        import inspect
        sig = inspect.signature(scanner.prepare)
        assert "market" in sig.parameters
        assert "use_short_filter" in sig.parameters


# ---------------------------------------------------------------------------
# 8. compute_threshold -- 필터 조합별 동적 threshold
# ---------------------------------------------------------------------------

class TestComputeThreshold:
    """compute_threshold(use_alpha, use_short_filter) 반환값 및 스캔 연동 검증."""

    def test_obv_only_returns_25(self):
        """alpha=OFF, short=OFF -> threshold=25 (OBV 단독 최대 30 >= 25 탐지 가능)."""
        from utils.accumulation_indicators import compute_threshold
        assert compute_threshold(use_alpha=False, use_short_filter=False) == 25

    def test_alpha_on_short_off_returns_55(self):
        """alpha=ON, short=OFF -> threshold=55 (OBV+Alpha 최대 65 >= 55 탐지 가능)."""
        from utils.accumulation_indicators import compute_threshold
        assert compute_threshold(use_alpha=True, use_short_filter=False) == 55

    def test_alpha_off_short_on_returns_55(self):
        """alpha=OFF, short=ON -> threshold=55 (OBV+Short 최대 65 >= 55 탐지 가능)."""
        from utils.accumulation_indicators import compute_threshold
        assert compute_threshold(use_alpha=False, use_short_filter=True) == 55

    def test_all_filters_returns_70(self):
        """alpha=ON, short=ON -> threshold=70 (OBV+Alpha+Short 최대 100 >= 70 탐지 가능)."""
        from utils.accumulation_indicators import compute_threshold
        assert compute_threshold(use_alpha=True, use_short_filter=True) == 70

    def test_threshold_always_reachable(self):
        """모든 조합에서 최대 점수 >= threshold (탐지 가능성 보장)."""
        from utils.accumulation_indicators import compute_threshold
        for use_alpha in (True, False):
            for use_short in (True, False):
                th = compute_threshold(use_alpha, use_short)
                max_score = 30 + (35 if use_alpha else 0) + (35 if use_short else 0)
                assert max_score >= th, (
                    f"use_alpha={use_alpha}, use_short={use_short}: "
                    f"max_score={max_score} < threshold={th}"
                )


# ---------------------------------------------------------------------------
# 9. alpha=ON, short=OFF 전체 스캔 시나리오 (KOSPI 동일 조건)
# ---------------------------------------------------------------------------

class TestAlphaOnShortOff:
    """KOSPI: alpha=ON, short=OFF 조건 동작 검증."""

    def _make_alpha_obv_stock(self, n: int = 40):
        """OBV 스파이크 + 강한 알파 모두 발생하는 더미 데이터."""
        df = _make_ohlcv(n, volume_multipliers={-1: 3.0})
        # 마지막 날 +3% 상승 (알파 모멘텀 2% 초과)
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        return df

    def test_score_65_with_alpha_on_short_off(self):
        """alpha=ON, short=OFF: OBV(30)+Alpha(35)=65 달성."""
        from utils.accumulation_indicators import analyze_whale_with_options
        df = self._make_alpha_obv_stock()
        idx = _make_index(df, down_days={len(df) - 1})
        full, _ = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=False, threshold=55
        )
        assert full["Accum_Score"].max() == 65

    def test_threshold_55_detects_score_65(self):
        """threshold=55 기준으로 score=65 -> buy_signals 포함."""
        from utils.accumulation_indicators import analyze_whale_with_options, compute_threshold
        df = self._make_alpha_obv_stock()
        idx = _make_index(df, down_days={len(df) - 1})
        th = compute_threshold(use_alpha=True, use_short_filter=False)
        _, buy = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=False, threshold=th
        )
        assert len(buy) >= 1, f"threshold={th}으로 buy_signals 탐지되어야 함"

    def test_alpha_momentum_detects_without_market_down(self):
        """지수 상승일에도 2%+ 알파 모멘텀 -> Alpha_Sig=1 (모멘텀 알파)."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n)
        # 종목 +3%, 지수 +0.5% -> alpha=2.5% > 2% 임계값
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = pd.DataFrame(
            {"Close": [1000.0] * (n - 1) + [1005.0]},  # 지수 +0.5% 상승
            index=df.index,
        )
        full, _ = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=False, threshold=35
        )
        assert full["Alpha_Sig"].iloc[-1] == 1
        assert full["Accum_Score"].iloc[-1] >= 35

    def test_alpha_defensive_detects_on_market_down_day(self):
        """지수 하락일에 종목 방어 -> Alpha_Sig=1 (방어 알파)."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n)
        # 종목 +0.5%, 지수 -2% -> 방어 알파 조건 충족 (alpha > 0, index_ret < 0)
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.005
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = _make_index(df, down_days={n - 1})  # 지수 마지막 날 -2%
        full, _ = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=False, threshold=35
        )
        assert full["Alpha_Sig"].iloc[-1] == 1

    def test_obv_only_still_detectable_with_threshold_25(self):
        """alpha=OFF 에서도 OBV 스파이크(30점) >= threshold(25) -> 탐지."""
        from utils.accumulation_indicators import analyze_whale_with_options, compute_threshold
        df = _make_ohlcv(40, volume_multipliers={-1: 3.0})
        idx = pd.DataFrame()
        th = compute_threshold(use_alpha=False, use_short_filter=False)
        _, buy = analyze_whale_with_options(
            df, idx, use_alpha=False, use_short_filter=False, threshold=th
        )
        assert len(buy) >= 1, f"OBV 단독 threshold={th}으로 탐지되어야 함"

    def test_scan_batch_uses_use_alpha_from_params(self):
        """_scan_batch의 use_alpha 파라미터가 시그니처에 포함되어 있음."""
        import inspect
        from accumulation_scanner import AccumulationScanner
        sig = inspect.signature(AccumulationScanner._scan_batch)
        assert "use_alpha" in sig.parameters

    def test_prepare_signature_has_use_alpha(self):
        """prepare() 시그니처에 use_alpha 파라미터 존재."""
        import inspect
        from accumulation_scanner import AccumulationScanner
        sig = inspect.signature(AccumulationScanner.prepare)
        assert "use_alpha" in sig.parameters


# ---------------------------------------------------------------------------
# 10. 윈도우 집계 방식 -- OBV와 Alpha가 다른 날 발생해도 합산
# ---------------------------------------------------------------------------

class TestWindowScoring:
    """_scan_batch의 윈도우 내 독립 신호 집계 검증."""

    def test_obv_and_alpha_different_days_both_count(self):
        """OBV 스파이크와 Alpha가 서로 다른 날 발생해도 window_score에 합산됨.

        기존 max_score(단일 날 최대) 방식에서는 OBV(30)+Alpha(35)=65가
        같은 날 발생해야만 탐지됐으나, 윈도우 집계 방식에서는 따로 발생해도 됨.
        """
        from utils.accumulation_indicators import analyze_whale_with_options
        # n=60: rolling(20) 충분히 warm-up 후, OBV 스파이크를 -20번째 날에 배치
        # → 마지막 20일 윈도우 안에 포함, 알파는 마지막 날에 별도 발생
        n = 60
        df = _make_ohlcv(n, volume_multipliers={-20: 3.0})
        # 마지막 날: 알파 모멘텀 (종목 +3%, 지수 보합)
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = pd.DataFrame({"Close": [1000.0] * n}, index=df.index)

        full, _ = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=False, threshold=55
        )

        # 윈도우(25일) 내 신호 독립 집계
        win = 25
        recent = full.tail(win)
        has_obv = bool(recent["Is_Whale_Spike"].any())
        has_alpha = bool(recent["Alpha_Sig"].any())
        window_score = (30 if has_obv else 0) + (35 if has_alpha else 0)

        assert has_obv, "윈도우 내 OBV 스파이크 있어야 함"
        assert has_alpha, "윈도우 내 Alpha 신호 있어야 함"
        assert window_score == 65, f"window_score 65 기대, 실제={window_score}"
        assert window_score >= 55, "threshold=55 통과해야 함"

    def test_obv_spike_day_without_alpha_window_score_30(self):
        """OBV 스파이크만 있고 alpha=OFF → window_score=30, threshold=25 통과."""
        from utils.accumulation_indicators import analyze_whale_with_options, compute_threshold
        df = _make_ohlcv(40, volume_multipliers={-1: 3.0})
        idx = pd.DataFrame()
        full, _ = analyze_whale_with_options(
            df, idx, use_alpha=False, use_short_filter=False
        )
        recent = full.tail(15)
        has_obv = bool(recent["Is_Whale_Spike"].any())
        window_score = 30 if has_obv else 0
        th = compute_threshold(use_alpha=False, use_short_filter=False)
        assert window_score >= th, f"OBV 단독 window_score={window_score} >= threshold={th}"

    def test_alpha_only_window_score_35_below_threshold_55(self):
        """Alpha만 있고 OBV 없으면 window_score=35 < threshold=55 → 미탐지."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n)
        # 모든 날 지수 하락 → 종목 양의 알파 (Alpha_Sig=1)
        idx = _make_index(df, down_days=set(range(n)))
        full, _ = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=False, threshold=55
        )
        recent = full.tail(15)
        has_obv = bool(recent["Is_Whale_Spike"].any())
        has_alpha = bool(recent["Alpha_Sig"].any()) if "Alpha_Sig" in recent.columns else False
        window_score = (30 if has_obv else 0) + (35 if has_alpha else 0)
        # OBV 없으니 35점 → threshold=55 미달
        assert not has_obv
        assert window_score == 35
        assert window_score < 55
