from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status


def install_error_handlers(app):
    @app.exception_handler(AppError)
    async def app_error(_request: Request, exc: AppError):
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        messages = []
        for error in exc.errors():
            field = str(error["loc"][-1])
            context = error.get("ctx", {})
            custom = context.get("error")
            messages.append(f"{field}: {custom}" if custom else f"Проверьте поле «{field}»: значение вне допустимого формата или диапазона")
        return JSONResponse({"code": "VALIDATION_ERROR", "message": "; ".join(messages)}, status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        messages = {404: "Не найдено", 401: "Требуется вход", 403: "Недостаточно прав", 405: "Метод не поддерживается"}
        return JSONResponse({"code": f"HTTP_{exc.status_code}", "message": messages.get(exc.status_code, "Запрос отклонён")}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, _exc: Exception):
        import logging
        logging.getLogger("taoji").error("unexpected_error type=%s", type(_exc).__name__)
        return JSONResponse({"code": "INTERNAL_ERROR", "message": "Не удалось выполнить запрос. Попробуйте ещё раз."}, status_code=500)
