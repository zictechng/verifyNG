from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class VerificationResult:
    """Standardized response from any KYC / business identity verification provider."""
    success: bool
    status: str  # 'verified', 'rejected', 'pending', 'error'
    provider_name: str
    reference_id: str = ""
    confidence_score: float = 0.0
    verified_data: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    raw_response: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_verified(self) -> bool:
        return self.success and self.status == 'verified'


class BaseVerificationProvider(ABC):
    """
    Abstract interface for all third-party identity & corporate verification providers.
    Enables swapping Smile ID, Dojah, Prembly, VerifyMe, or custom engines seamlessly.
    """
    provider_name: str = "base"

    @abstractmethod
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
        """
        Validate legal existence and corporate standing of a company.
        """
        pass

    @abstractmethod
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
        """
        Validate an authorized representative or individual merchant identity.
        """
        pass
