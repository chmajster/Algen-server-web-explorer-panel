from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from ...identity.permissions import authorize
from ...package_center.models import api_error
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from .rbac import IMAGE_CONVERTER_CONVERT, IMAGE_CONVERTER_VIEW
from .service import MAX_BATCH_BYTES, MAX_FILE_BYTES, MAX_UPLOAD_FILES, ImageConverterError, service

router = APIRouter(prefix="/api/modules/image-converter", tags=["image-converter"])


class DirectoryConversionRequest(BaseModel):
    source_directory: str = Field(min_length=1, max_length=4096)
    output_directory: str | None = Field(default=None, max_length=4096)
    format: str = Field(default="webp", min_length=2, max_length=16)
    quality: int = Field(default=90, ge=1, le=100)
    recursive: bool = False


def _fail(error: ImageConverterError) -> None:
    status = 422
    if error.code in {"DIRECTORY_NOT_FOUND", "BATCH_NOT_FOUND"}:
        status = 404
    elif error.code in {"FILE_TOO_LARGE", "TOO_MANY_FILES"}:
        status = 413
    api_error(status, error.code, str(error))


@router.get("/formats")
def formats(user: SessionUser = Depends(current_user)):
    authorize(user, IMAGE_CONVERTER_VIEW)
    return {"formats": service.formats()}


@router.get("/browse")
def browse(path: str | None = None, user: SessionUser = Depends(current_user)):
    authorize(user, IMAGE_CONVERTER_VIEW)
    try:
        return service.browse(user.username, path)
    except ImageConverterError as error:
        _fail(error)


@router.post("/directory")
def convert_directory(payload: DirectoryConversionRequest, user: SessionUser = Depends(mutating_user)):
    authorize(user, IMAGE_CONVERTER_CONVERT)
    try:
        return service.convert_directory(
            user.username,
            payload.source_directory,
            payload.output_directory,
            payload.format,
            payload.quality,
            payload.recursive,
        )
    except ImageConverterError as error:
        _fail(error)


@router.post("/upload")
async def convert_upload(
    files: list[UploadFile] = File(...),
    output_format: str = Form("webp"),
    quality: int = Form(90),
    user: SessionUser = Depends(mutating_user),
):
    authorize(user, IMAGE_CONVERTER_CONVERT)
    if not files:
        api_error(422, "NO_IMAGES", "At least one image is required")
    if len(files) > MAX_UPLOAD_FILES:
        api_error(413, "TOO_MANY_FILES", f"A temporary upload is limited to {MAX_UPLOAD_FILES} images")
    batch_id = service.create_batch(user.username)
    total = 0
    try:
        for index, upload in enumerate(files, start=1):
            content = await upload.read(MAX_FILE_BYTES + 1)
            await upload.close()
            if len(content) > MAX_FILE_BYTES:
                raise ImageConverterError("FILE_TOO_LARGE", f"Each uploaded image is limited to {MAX_FILE_BYTES // (1024 * 1024)} MB")
            total += len(content)
            if total > MAX_BATCH_BYTES:
                raise ImageConverterError("BATCH_TOO_LARGE", f"A temporary upload is limited to {MAX_BATCH_BYTES // (1024 * 1024)} MB")
            service.add_upload(user.username, batch_id, upload.filename, content, index)
        return service.convert_batch(user.username, batch_id, output_format, quality)
    except ImageConverterError as error:
        service.delete_batch(user.username, batch_id)
        _fail(error)


@router.get("/download/{batch_id}")
def download(batch_id: str, user: SessionUser = Depends(current_user)):
    authorize(user, IMAGE_CONVERTER_CONVERT)
    try:
        archive = service.archive(user.username, batch_id)
    except ImageConverterError as error:
        _fail(error)
    return FileResponse(
        path=archive,
        filename="converted-images.zip",
        media_type="application/zip",
        background=BackgroundTask(service.delete_batch, user.username, batch_id),
    )
