#
# wallet_pass.py
# API endpoints for Apple Wallet pass creation
#

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.api.deps import get_current_db_user
from app.models.user import User
from app.schemas.wallet_pass import WalletPassCreateRequest, WalletPassCreateResponse
from app.services.wallet_pass_service import wallet_pass_service
import base64

router = APIRouter(prefix="/wallet-pass", tags=["wallet-pass"])


@router.post("/create", response_model=WalletPassCreateResponse)
async def create_wallet_pass(
    request: WalletPassCreateRequest,
    current_user: User = Depends(get_current_db_user)
):
    """
    Create a signed Apple Wallet pass (.pkpass file).

    The pass is returned as base64-encoded data that can be
    used with PKAddPassesViewController on iOS.
    """
    success, pass_data, error = await wallet_pass_service.create_pass(request)

    if not success:
        return WalletPassCreateResponse(
            success=False,
            pass_data=None,
            error=error or "Failed to create pass"
        )

    # Encode pass data as base64
    pass_base64 = base64.b64encode(pass_data).decode('utf-8')

    return WalletPassCreateResponse(
        success=True,
        pass_data=pass_base64,
        error=None
    )


@router.post("/create-download")
async def create_wallet_pass_download(
    request: WalletPassCreateRequest,
    current_user: User = Depends(get_current_db_user)
):
    """
    Create and directly download a .pkpass file.

    This endpoint returns the raw .pkpass file for direct download.
    """
    success, pass_data, error = await wallet_pass_service.create_pass(request)

    if not success:
        raise HTTPException(status_code=400, detail=error or "Failed to create pass")

    return Response(
        content=pass_data,
        media_type="application/vnd.apple.pkpass",
        headers={
            "Content-Disposition": f"attachment; filename={request.store_name.replace(' ', '_')}_pass.pkpass"
        }
    )
