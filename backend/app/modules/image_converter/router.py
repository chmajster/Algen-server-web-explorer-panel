from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from ...identity.permissions import authorize
from ...package_center.models import api_error
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from .rbac import IMAGE_CONVERTER_CONVERT, IMAGE_CONVERTER_VIEW
from .service import MAX_BATCH_BYTES, MAX_DIMENSION, MAX_FILE_BYTES, MAX_UPLOAD_FILES, ImageConverterError, service

router = APIRouter(prefix="/api/modules/image-converter", tags=["image-converter"])

PUBLIC_ERROR_MESSAGES: dict[str, str] = {
    "ANIMATED_IMAGE_UNSUPPORTED": "Animated images are not supported",
    "BATCH_NOT_FOUND": "Converted temporary files are no longer available",
    "BATCH_TOO_LARGE": "The temporary upload exceeds the allowed total size",
    "CONVERSION_FAILED": "None of the uploaded images could be converted",
    "DIRECTORY_NOT_FOUND": "Selected directory does not exist",
    "DIRECTORY_UNREADABLE": "Selected directory cannot be read",
    "FILE_TOO_LARGE": "An uploaded image exceeds the allowed file size",
    "IMAGE_TOO_LARGE": "An image exceeds the allowed pixel count",
    "INVALID_BATCH": "Invalid temporary batch identifier",
    "INVALID_DIMENSION": "Invalid target image dimensions",
    "INVALID_IMAGE": "An image could not be decoded or converted",
    "INVALID_OVERWRITE_POLICY": "Invalid overwrite policy",
    "INVALID_QUALITY": "Invalid image quality value",
    "NAME_COLLISION": "A unique output filename could not be created",
    "NO_IMAGES": "No supported images were found",
    "TOO_MANY_FILES": "Too many images were provided",
    "UNSUPPORTED_FORMAT": "Unsupported output image format",
    "UNSUPPORTED_INPUT": "Unsupported input image format",
    "WRITE_FAILED": "A converted image could not be written",
}


class DirectoryConversionRequest(BaseModel):
    source_directory: str = Field(min_length=1, max_length=4096)
    output_directory: str | None = Field(default=None, max_length=4096)
    format: str = Field(default="webp", min_length=2, max_length=16)
    quality: int = Field(default=90, ge=1, le=100)
    recursive: bool = False
    width: int | None = Field(default=None, ge=1, le=MAX_DIMENSION)
    height: int | None = Field(default=None, ge=1, le=MAX_DIMENSION)
    keep_aspect: bool = True
    strip_metadata: bool = True
    prefix: str = Field(default="", max_length=80)
    suffix: str = Field(default="", max_length=80)
    overwrite_policy: str = Field(default="rename", pattern="^(rename|skip|overwrite)$")


def _fail(error: ImageConverterError) -> NoReturn:
    status = 422
    if error.code in {"DIRECTORY_NOT_FOUND", "BATCH_NOT_FOUND"}:
        status = 404
    elif error.code in {"FILE_TOO_LARGE", "TOO_MANY_FILES", "BATCH_TOO_LARGE"}:
        status = 413
    message = PUBLIC_ERROR_MESSAGES.get(error.code, "Image conversion request failed")
    api_error(status, error.code, message)


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
            payload.width,
            payload.height,
            payload.keep_aspect,
            payload.strip_metadata,
            payload.prefix,
            payload.suffix,
            payload.overwrite_policy,
        )
    except ImageConverterError as error:
        _fail(error)


@router.post("/upload")
async def convert_upload(
    files: list[UploadFile] = File(...),
    output_format: str = Form("webp"),
    quality: int = Form(90),
    width: int | None = Form(None),
    height: int | None = Form(None),
    keep_aspect: bool = Form(True),
    strip_metadata: bool = Form(True),
    prefix: str = Form(""),
    suffix: str = Form(""),
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
        return service.convert_batch(user.username, batch_id, output_format, quality, width, height, keep_aspect, strip_metadata, prefix, suffix)
    except ImageConverterError as error:
        service.delete_batch(user.username, batch_id)
        _fail(error)


@router.get("/download/{batch_id}")
def download(batch_id: UUID, user: SessionUser = Depends(current_user)):
    authorize(user, IMAGE_CONVERTER_CONVERT)
    canonical_batch_id = batch_id.hex
    try:
        archive = service.archive(user.username, canonical_batch_id)
    except ImageConverterError as error:
        _fail(error)
    return FileResponse(
        path=archive,
        filename="converted-images.zip",
        media_type="application/zip",
        background=BackgroundTask(service.delete_batch, user.username, canonical_batch_id),
    )
