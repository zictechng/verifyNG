import uuid
import logging
from typing import Optional, Any
from .base import BaseVerificationProvider, VerificationResult

logger = logging.getLogger(__name__)


class MockVerificationProvider(BaseVerificationProvider):
    """
    Simulated verification provider for development, QA, and local testing.
    Validates regex formatting without burning live third-party billing credits.
    """
    provider_name = "mock_provider"

    def verify_business(
        self,
        country: str,
        company_name: str,
        reg_number: str,
        reg_type: str = "",
        document_file: Optional[Any] = None,
        tax_id: str = "",
        **kwargs
    ) -> VerificationResult:
        logger.info(f"[MockProvider] Verifying business: {company_name} ({reg_number}) [{country}]")
        clean_num = reg_number.strip().upper()

        if "REJECT" in clean_num or "FAIL" in clean_num:
            return VerificationResult(
                success=False,
                status="rejected",
                provider_name=self.provider_name,
                reference_id=f"MOCK-BIZ-{uuid.uuid4().hex[:10].upper()}",
                confidence_score=0.0,
                error_message=f"Corporate registry records could not authenticate {clean_num} in {country}.",
                raw_response={"simulated": True, "reason": "Test rejection triggered"}
            )

        return VerificationResult(
            success=True,
            status="verified",
            provider_name=self.provider_name,
            reference_id=f"MOCK-BIZ-{uuid.uuid4().hex[:10].upper()}",
            confidence_score=98.5,
            verified_data={
                "company_name": company_name,
                "reg_number": clean_num,
                "country": country,
                "status": "Active / Good Standing",
                "registration_date": "2021-04-15",
                "authority": reg_type or "National Corporate Affairs Registry",
            },
            raw_response={"simulated": True, "match": True}
        )

    def verify_identity(
        self,
        country: str,
        doc_type: str,
        id_number: str,
        full_name: str = "",
        doc_file: Optional[Any] = None,
        selfie_file: Optional[Any] = None,
        require_liveness: bool = False,
        **kwargs
    ) -> VerificationResult:
        logger.info(f"[MockProvider] Verifying identity: {full_name} ({doc_type}: {id_number}) [{country}]")
        clean_id = id_number.strip().upper()

        if "REJECT" in clean_id or "FAIL" in clean_id:
            return VerificationResult(
                success=False,
                status="rejected",
                provider_name=self.provider_name,
                reference_id=f"MOCK-ID-{uuid.uuid4().hex[:10].upper()}",
                confidence_score=12.0,
                error_message="The identification details could not be matched against authoritative civil records.",
                raw_response={"simulated": True, "reason": "Test rejection triggered"}
            )

        return VerificationResult(
            success=True,
            status="verified",
            provider_name=self.provider_name,
            reference_id=f"MOCK-ID-{uuid.uuid4().hex[:10].upper()}",
            confidence_score=96.0,
            verified_data={
                "full_name": full_name,
                "id_number": clean_id,
                "doc_type": doc_type,
                "country": country,
                "face_match_confidence": 94.2 if selfie_file else None,
                "liveness_passed": True if require_liveness else None,
            },
            raw_response={"simulated": True, "match": True}
        )
