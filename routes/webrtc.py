from fastapi import APIRouter
from pydantic import BaseModel

from services.webrtc import (
    create_answer
)


class Offer(BaseModel):

    sdp: str
    type: str


def register_webrtc_routes(
    app
):

    router = APIRouter()

    @router.post("/offer")
    async def offer(
        data: Offer
    ):

        return await create_answer(
            data.sdp,
            data.type
        )

    app.include_router(
        router
    )