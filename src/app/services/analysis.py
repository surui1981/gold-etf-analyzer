"""机会分析编排服务：串联评分引擎与记录持久化。"""

import json

from app.repositories.analysis import AnalysisRepository
from app.schemas.analysis import AnalysisRecordOut, OpportunityRequest, OpportunityResponse
from app.services.scoring import OpportunityScoringService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AnalysisService:
    """业务编排层：评分 + 落库 + 历史查询。

    服务层不感知 HTTP，只面向领域对象，便于单元测试与复用。
    """

    def __init__(
        self,
        repo: AnalysisRepository,
        scoring: OpportunityScoringService,
    ) -> None:
        self._repo = repo
        self._scoring = scoring

    async def evaluate(self, request: OpportunityRequest) -> OpportunityResponse:
        """执行宏观因子评分并持久化分析记录。

        Args:
            request: 机会分析请求

        Returns:
            带 record_id 的机会分析结果

        Raises:
            SQLAlchemyError: 记录持久化失败
        """
        result = self._scoring.evaluate(request.factors)
        factors_detail = json.dumps(
            [f.model_dump() for f in result.factors], ensure_ascii=False
        )
        record = await self._repo.create(
            dxy=request.factors.dxy,
            us10y_yield=request.factors.us10y_yield,
            real_rate=request.factors.real_rate,
            inflation_expectation=request.factors.inflation_expectation,
            risk_off=request.factors.risk_off,
            score=result.score,
            window=result.window.value,
            signal=result.signal.value,
            factors_detail=factors_detail,
        )
        logger.info(
            "Opportunity evaluated: id=%s score=%s window=%s",
            record.id, result.score, result.window.value,
        )
        return result.model_copy(update={"record_id": record.id})

    async def list_history(self, limit: int = 20) -> list[AnalysisRecordOut]:
        """返回最近的分析记录（按时间倒序）。

        Args:
            limit: 返回条数上限

        Returns:
            历史记录列表（ORM → Pydantic 输出模型）
        """
        records = await self._repo.list_recent(limit=limit)
        return [AnalysisRecordOut.model_validate(r) for r in records]
