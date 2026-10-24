from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.deps import current_user
from app.errors import AppError
from app.services.products import ProductService


class PreviewIn(BaseModel):
    url: str = Field(min_length=1, max_length=4096)


def make_router(limiter):
    router = APIRouter(prefix="/products", tags=["Товары по ссылке"])

    def service(request: Request):
        if not hasattr(request.app.state, "products"):
            request.app.state.products = ProductService(request.app.state.settings)
        return request.app.state.products

    @router.post("/preview", dependencies=[Depends(current_user)])
    @limiter.limit("20/minute")
    async def preview(request: Request, data: PreviewIn):
        return await service(request).preview(data.url)

    @router.get("/image")
    @limiter.limit("120/minute")
    async def image(request: Request, t: str = ""):
        result = await service(request).image(t)
        if result is None:
            raise AppError("IMAGE_UNAVAILABLE", "Изображение недоступно", 404)
        body, media = result
        return Response(body, media_type=media,
                        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})

    return router
