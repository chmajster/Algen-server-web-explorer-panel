from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener
except ImportError:  # pragma: no cover - dependency is pinned in production
    register_heif_opener = None
else:
    register_heif_opener()

from ...path_policy import resolve_user_path
from ...write_policy import assert_write_allowed

MAX_UPLOAD_FILES = 100
MAX_DIRECTORY_FILES = 500
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_BATCH_BYTES = 500 * 1024 * 1024
MAX_PIXELS = 100_000_000
TEMP_TTL_SECONDS = 60 * 60
INPUT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif"}
OUTPUT_FORMATS: dict[str, tuple[str, str, bool]] = {
    "jpeg": ("JPEG", ".jpg", True),
    "png": ("PNG", ".png", False),
    "webp": ("WEBP", ".webp", True),
    "avif": ("AVIF", ".avif", True),
    "tiff": ("TIFF", ".tiff", False),
    "bmp": ("BMP", ".bmp", False),
}


class ImageConverterError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ConvertedFile:
    source: str
    output: str
    size: int


def _normalise_format(value: str) -> str:
    fmt = value.strip().lower()
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt not in OUTPUT_FORMATS:
        raise ImageConverterError("UNSUPPORTED_FORMAT", f"Unsupported output format: {value}")
    return fmt


def _normalise_quality(value: int) -> int:
    if value < 1 or value > 100:
        raise ImageConverterError("INVALID_QUALITY", "Quality must be between 1 and 100")
    return value


def _flatten_alpha(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ImageConverterError("NAME_COLLISION", f"Could not create a unique output name for {path.name}")


def _safe_filename(value: str | None, index: int) -> str:
    name = Path((value or "").replace("\\", "/")).name.replace("\x00", "").strip()
    return name or f"image-{index}"


def convert_image(source: Path, destination: Path, output_format: str, quality: int = 90) -> ConvertedFile:
    fmt = _normalise_format(output_format)
    quality = _normalise_quality(quality)
    pillow_format, _extension, lossy = OUTPUT_FORMATS[fmt]
    try:
        with Image.open(source) as opened:
            if opened.width * opened.height > MAX_PIXELS:
                raise ImageConverterError("IMAGE_TOO_LARGE", f"Image exceeds {MAX_PIXELS:,} pixels")
            if getattr(opened, "is_animated", False) and getattr(opened, "n_frames", 1) > 1:
                raise ImageConverterError("ANIMATED_IMAGE_UNSUPPORTED", "Animated images are not supported")
            image = ImageOps.exif_transpose(opened)
            if fmt in {"jpeg", "bmp"}:
                image = _flatten_alpha(image)
            elif image.mode not in {"RGB", "RGBA", "L", "LA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            destination.parent.mkdir(parents=True, exist_ok=True)
            options: dict[str, object] = {}
            if lossy:
                options["quality"] = quality
            if fmt == "jpeg":
                options.update(optimize=True, progressive=True)
            elif fmt == "png":
                options["optimize"] = True
            elif fmt == "tiff":
                options["compression"] = "tiff_deflate"
            image.save(destination, pillow_format, **options)
    except ImageConverterError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageConverterError("INVALID_IMAGE", f"Cannot decode or convert {source.name}") from exc
    return ConvertedFile(str(source), str(destination), destination.stat().st_size)


class ImageConverterService:
    def __init__(self, temp_root: Path | None = None):
        self.temp_root = temp_root or Path(tempfile.gettempdir()) / "webnas-image-converter"

    def formats(self) -> list[dict[str, object]]:
        return [
            {"id": key, "extension": extension, "lossy": lossy}
            for key, (_pillow, extension, lossy) in OUTPUT_FORMATS.items()
        ]

    def browse(self, username: str, path: str | None) -> dict[str, object]:
        target = resolve_user_path(username, path)
        if not target.exists() or not target.is_dir():
            raise ImageConverterError("DIRECTORY_NOT_FOUND", "Selected directory does not exist")
        directories: list[dict[str, str]] = []
        images: list[dict[str, object]] = []
        try:
            children = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        except OSError as exc:
            raise ImageConverterError("DIRECTORY_UNREADABLE", "Selected directory cannot be read") from exc
        for child in children[:1000]:
            if child.is_dir():
                directories.append({"name": child.name, "path": str(child)})
            elif child.is_file() and child.suffix.lower() in INPUT_EXTENSIONS:
                try:
                    size = child.stat().st_size
                except OSError:
                    size = 0
                images.append({"name": child.name, "path": str(child), "size": size})
        parent: str | None = None
        try:
            parent_path = resolve_user_path(username, str(target.parent))
            if parent_path != target:
                parent = str(parent_path)
        except Exception:
            parent = None
        return {
            "path": str(target),
            "parent": parent,
            "directories": directories,
            "images": images,
            "truncated": len(children) > 1000,
        }

    def convert_directory(self, username: str, source_directory: str, output_directory: str | None, output_format: str, quality: int, recursive: bool) -> dict[str, object]:
        fmt = _normalise_format(output_format)
        quality = _normalise_quality(quality)
        source = resolve_user_path(username, source_directory)
        if not source.exists() or not source.is_dir():
            raise ImageConverterError("DIRECTORY_NOT_FOUND", "Selected source directory does not exist")
        output = resolve_user_path(username, output_directory or str(source / f"converted-{fmt}"))
        assert_write_allowed(output)
        iterator = source.rglob("*") if recursive else source.iterdir()
        candidates: list[Path] = []
        for item in iterator:
            if len(candidates) > MAX_DIRECTORY_FILES:
                break
            try:
                item.relative_to(output)
                continue
            except ValueError:
                pass
            if item.is_file() and item.suffix.lower() in INPUT_EXTENSIONS:
                candidates.append(item)
        if len(candidates) > MAX_DIRECTORY_FILES:
            raise ImageConverterError("TOO_MANY_FILES", f"A directory conversion is limited to {MAX_DIRECTORY_FILES} images")
        if not candidates:
            raise ImageConverterError("NO_IMAGES", "No supported images were found in the selected directory")
        _pillow, extension, _lossy = OUTPUT_FORMATS[fmt]
        converted: list[dict[str, object]] = []
        failed: list[dict[str, str]] = []
        for source_file in candidates:
            relative = source_file.relative_to(source)
            target = _unique_destination(output / relative.parent / f"{source_file.stem}{extension}")
            try:
                assert_write_allowed(target)
                converted.append(asdict(convert_image(source_file, target, fmt, quality)))
            except ImageConverterError as exc:
                failed.append({"source": str(source_file), "code": exc.code, "message": str(exc)})
            except OSError as exc:
                failed.append({"source": str(source_file), "code": "WRITE_FAILED", "message": str(exc)})
        return {"output_directory": str(output), "format": fmt, "converted": converted, "failed": failed}

    def _user_temp_root(self, username: str) -> Path:
        digest = hashlib.sha256(username.encode("utf-8")).hexdigest()[:20]
        return self.temp_root / digest

    def cleanup_stale(self, username: str) -> None:
        root = self._user_temp_root(username)
        if not root.exists():
            return
        cutoff = time.time() - TEMP_TTL_SECONDS
        for entry in root.iterdir():
            try:
                if entry.is_dir() and entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                continue

    def create_batch(self, username: str) -> str:
        self.cleanup_stale(username)
        batch_id = uuid.uuid4().hex
        directory = self._user_temp_root(username) / batch_id
        directory.mkdir(parents=True, mode=0o700)
        return batch_id

    def _batch_dir(self, username: str, batch_id: str) -> Path:
        if len(batch_id) != 32 or any(character not in "0123456789abcdef" for character in batch_id):
            raise ImageConverterError("INVALID_BATCH", "Invalid temporary batch identifier")
        return self._user_temp_root(username) / batch_id

    def add_upload(self, username: str, batch_id: str, filename: str | None, content: bytes, index: int) -> Path:
        if len(content) > MAX_FILE_BYTES:
            raise ImageConverterError("FILE_TOO_LARGE", f"Each uploaded image is limited to {MAX_FILE_BYTES // (1024 * 1024)} MB")
        name = _safe_filename(filename, index)
        if Path(name).suffix.lower() not in INPUT_EXTENSIONS:
            raise ImageConverterError("UNSUPPORTED_INPUT", f"Unsupported input file: {name}")
        inputs = self._batch_dir(username, batch_id) / "input"
        inputs.mkdir(parents=True, mode=0o700, exist_ok=True)
        destination = _unique_destination(inputs / name)
        destination.write_bytes(content)
        return destination

    def convert_batch(self, username: str, batch_id: str, output_format: str, quality: int) -> dict[str, object]:
        fmt = _normalise_format(output_format)
        quality = _normalise_quality(quality)
        batch = self._batch_dir(username, batch_id)
        inputs = batch / "input"
        files = sorted(item for item in inputs.iterdir() if item.is_file()) if inputs.exists() else []
        if not files:
            raise ImageConverterError("NO_IMAGES", "No images were uploaded")
        if len(files) > MAX_UPLOAD_FILES:
            raise ImageConverterError("TOO_MANY_FILES", f"A temporary upload is limited to {MAX_UPLOAD_FILES} images")
        _pillow, extension, _lossy = OUTPUT_FORMATS[fmt]
        outputs = batch / "output"
        converted: list[dict[str, object]] = []
        failed: list[dict[str, str]] = []
        for source in files:
            destination = _unique_destination(outputs / f"{source.stem}{extension}")
            try:
                converted.append(asdict(convert_image(source, destination, fmt, quality)))
            except ImageConverterError as exc:
                failed.append({"source": source.name, "code": exc.code, "message": str(exc)})
        shutil.rmtree(inputs, ignore_errors=True)
        if not converted:
            raise ImageConverterError("CONVERSION_FAILED", "None of the uploaded images could be converted")
        archive = batch / "converted-images.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for item in sorted(outputs.iterdir()):
                if item.is_file():
                    bundle.write(item, arcname=item.name)
        shutil.rmtree(outputs, ignore_errors=True)
        return {
            "batch_id": batch_id,
            "format": fmt,
            "converted": converted,
            "failed": failed,
            "download_url": f"/api/modules/image-converter/download/{batch_id}",
        }

    def archive(self, username: str, batch_id: str) -> Path:
        self.cleanup_stale(username)
        archive = self._batch_dir(username, batch_id) / "converted-images.zip"
        if not archive.exists() or not archive.is_file():
            raise ImageConverterError("BATCH_NOT_FOUND", "Converted temporary files are no longer available")
        return archive

    def delete_batch(self, username: str, batch_id: str) -> None:
        try:
            shutil.rmtree(self._batch_dir(username, batch_id), ignore_errors=True)
        except ImageConverterError:
            return


service = ImageConverterService()
