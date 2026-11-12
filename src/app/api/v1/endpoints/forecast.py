"""金价区间预测端点（V0.127.0）。

两个 GET：

- ``/price`` —— 未来 N 个交易日的金价区间（扇形路径 + **实测**覆盖率）；
- ``/calibration`` —— 校准产物（供页面展示「这个区间历史上准不准」）。

⚠ **这个接口不做方向预测** —— ``drift_mode`` 恒为 ``"none"``，
区间中心恒等于基准收盘价。任何「看多/看空」字段都不该出现在这里。
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_price_forecast_service
from app.schemas.forecast import (
    ForecastCalibrationOut,
    ForecastCrossCheckOut,
    ForecastMeasuredOut,
    ForecastPointOut,
    PriceForecastOut,
)
from app.services.price_forecast import (
    COVERAGE_Z,
    DEFAULT_COVERAGE,
    DEFAULT_HORIZON,
    DEFAULT_TARGET,
    PriceForecastService,
    cone_shape,
    load_calibration,
    load_shape,
    load_shape_stability,
)

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get(
    "/price",
    response_model=PriceForecastOut,
    summary="未来 N 个交易日的金价区间",
)
async def get_price_forecast(
    target: str = Query(
        DEFAULT_TARGET,
        pattern="^(ny|etf|gram)$",
        description="标的：ny=COMEX 纽约金（默认，V0.127.0 只交付这个）/ etf=518880 / gram=上海金",
    ),
    horizon: int = Query(DEFAULT_HORIZON, ge=5, le=60, description="期限（交易日，5-60；默认 20）"),
    coverage: float = Query(
        DEFAULT_COVERAGE,
        description="名义覆盖率：0.5 / 0.8 / 0.9 / 0.98（默认 0.8）",
    ),
    service: PriceForecastService = Depends(get_price_forecast_service),
) -> PriceForecastOut:
    """未来 N 个交易日的金价区间。

    ⚠ 响应里的 ``measured.out_of_sample`` 是**实测**覆盖率（样本外 walk-forward），
    通常略低于 ``coverage``（名义值）⇒ 页面上要显示实测值。
    """
    if coverage not in COVERAGE_Z:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的覆盖率 {coverage}；可用：{sorted(COVERAGE_Z)}",
        )
    try:
        fc = await service.build(target=target, horizon=horizon, coverage=coverage)
    except ValueError as exc:
        # 数据不足 / 口径不支持 ⇒ 400 而不是 500（前端可据此显示「样本不足」）
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    band = fc.band
    points = [
        ForecastPointOut(
            k=pt.k,
            date=fc.dates[pt.k - 1] if pt.k - 1 < len(fc.dates) else None,
            lower=round(pt.lower, 2),
            upper=round(pt.upper, 2),
        )
        for pt in band.points
    ]

    calibration = load_calibration(target)
    measured_entry = {}
    if calibration:
        coverages = calibration.get("coverages") or {}
        measured_entry = coverages.get(str(round(coverage * 100))) or {}

    normal_band = None
    ratio = None
    if band.ewma_half_width and band.analog_half_width and band.ewma_half_width > 0:
        ratio = band.analog_half_width / band.ewma_half_width
    if calibration:
        cc = calibration.get("cross_check") or {}
        p05, p95 = cc.get("p05"), cc.get("p95")
        if isinstance(p05, (int, float)) and isinstance(p95, (int, float)):
            normal_band = [round(float(p05), 4), round(float(p95), 4)]

    return PriceForecastOut(
        target=target,
        base_date=band.base_date,
        base_close=round(band.base_close, 2),
        horizon=horizon,
        coverage=coverage,
        z=band.z,
        sigma=round(band.sigma, 6),
        sigma_annual=round(band.sigma_annual, 2),
        method=band.method,
        drift_mode=band.drift_mode,
        shape_source=band.shape_source,
        lower=round(band.lower, 2),
        upper=round(band.upper, 2),
        points=points,
        measured=ForecastMeasuredOut(
            nominal=coverage,
            train=measured_entry.get("train"),
            out_of_sample=measured_entry.get("out_of_sample"),
            recent=measured_entry.get("recent"),
            source=fc.measured_source,
            n_out_of_sample=measured_entry.get("n_out_of_sample"),
        ),
        cross_check=ForecastCrossCheckOut(
            status=band.cross_check,
            ratio=round(ratio, 4) if ratio is not None else None,
            normal_band=normal_band,
            ewma_half_width=round(band.ewma_half_width, 6) if band.ewma_half_width else None,
            analog_half_width=round(band.analog_half_width, 6) if band.analog_half_width else None,
            analog_n_sim=band.analog_n_sim,
        ),
        reason=band.reason,
        n_bars=band.n_bars,
        first_date=band.first_date,
        min_sim=band.min_sim,
        generated_at=fc.generated_at,
    )


@router.get(
    "/calibration",
    response_model=ForecastCalibrationOut,
    summary="区间带的校准产物（实测覆盖率）",
)
async def get_forecast_calibration(
    target: str = Query(DEFAULT_TARGET, pattern="^(ny|etf|gram)$", description="标的"),
) -> ForecastCalibrationOut:
    """返回离线校准产物：各覆盖率档的实测覆盖率、样本量、两法交叉校验统计。

    ⚠ 附带**扇形形状曲线**（``shape``）与对数正态 √k 锥（``cone``）——
    前端「形状对照图」要画的就是这两条线。``shape`` 缺失时返回空数组，
    前端只画锥并明示「形状产物缺失」，**不拿锥冒充类比形状**。
    """
    data = load_calibration(target)
    horizon = int((data or {}).get("horizon", DEFAULT_HORIZON))
    shape = load_shape(horizon, target=target) or []
    cone = cone_shape(horizon)
    # ⚠ 跨窗口稳定性证据（V0.127.1）：页面要靠它**现算**跨窗口的短端倍数，
    #   写死的数字会随产物重算而变成假话。
    stability = load_shape_stability(horizon, target=target) or {}
    if not data:
        return ForecastCalibrationOut(
            target=target,
            horizon=horizon,
            available=False,
            notes=["no_calibration_artifact"],
            shape=shape,
            cone=cone,
            shape_stability=stability,
        )
    return ForecastCalibrationOut(
        target=data.get("target", target),
        horizon=horizon,
        generated_at=data.get("generated_at"),
        method=data.get("method"),
        source=data.get("source") or {},
        params=data.get("params") or {},
        spans=data.get("spans") or {},
        coverages=data.get("coverages") or {},
        cross_check=data.get("cross_check") or {},
        notes=data.get("notes") or [],
        available=True,
        shape=shape,
        cone=cone,
        shape_stability=stability,
    )
