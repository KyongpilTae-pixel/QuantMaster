class InvestmentReasoning:
    @staticmethod
    def generate_report(
        name: str,
        pbr: float,
        vwap_p: int,
        mfi: float,
        vwap_price: float,
    ) -> tuple[str, str]:
        buy_reason = (
            f"[매수 근거] {name}은(는) 자산 가치 대비 할인된 상태(PBR {pbr:.2f}) 에서 "
            f"최근 {vwap_p}일 VWAP(주요 추세선)을 거래량 동반하여 상향 돌파했습니다. "
            f"MFI {mfi:.1f}로 스마트 머니 유입이 포착되었으며 OBV 상승세가 수급을 뒷받침합니다."
        )
        sell_guide = (
            f"[매도 가이드] 현재가가 {format(int(vwap_price), ',')}원(VWAP {vwap_p}일 지지선)을 "
            f"종가 기준으로 하향 이탈하면 손절 원칙에 따른 매물 소화를 권장합니다. "
            f"목표가는 직전 고점 또는 VWAP 대비 +5~10% 수준을 기준으로 설정하십시오."
        )
        return buy_reason, sell_guide
