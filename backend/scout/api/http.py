from fastapi import APIRouter

from scout.contract import CONTRACT_VERSION

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "contract_version": CONTRACT_VERSION}


@router.get("/contract")
def contract() -> dict:
    return {"contract_version": CONTRACT_VERSION}
