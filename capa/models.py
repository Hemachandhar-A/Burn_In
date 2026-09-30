from datetime import datetime
from pydantic import BaseModel
from typing import Literal

# TEMP stubs for missing contracts
class TEMP_CapaRecord(BaseModel):
    id: str
    project_id: str
    trigger_reason: str
    status: Literal["OPEN", "RESOLVED"]
    owner_account_id: str | None
    created_at: datetime
    resolved_at: datetime | None

class TEMP_ResolveRequest(BaseModel):
    rationale: str
