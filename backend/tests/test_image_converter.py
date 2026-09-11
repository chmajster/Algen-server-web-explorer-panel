from __future__ import annotations

import importlib
import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.modules.image_converter.service import ImageConverterError, ImageConverterService, convert_image

image_service_module = importlib.import_module("app.modules.image_converter.service")


def image_bytes(mode: str = "RGB", color=(120, 30, 200), size=(24, 16)) -> bytes:
    stream = io.BytesIO()
    Image.new(mode, size, color).save(stream, "PNG")
    return stream.getvalue()


def test_convert_image_flattens_alpha_for_jpeg(tmp_path: Path):
    source = tmp_path / "alpha.png"
    source.write_bytes(image_bytes("RGBA", (255, 0, 0, 80)))
    output = tmp_path / "converted.jpg"

    result = convert_image(source, output, "jpeg", 85)

    assert result.output == str(output)
    assert result.source_size == source.stat().st_size
    with Image.open(output) as converted:
        assert converted.format == "JPEG"
        assert converted.mode == "RGB"
        assert converted.size == (24, 16)


def test_convert_image_rejects_unknown_output_format(tmp_path: Path):
    source = tmp_path / "source.png"
    source.write_bytes(image_bytes())
    with pytest.raises(ImageConverterError) as error:
        convert_image(source, tmp_path / "out.xyz", "xyz")
    assert error.value.code == "UNSUPPORTED_FORMAT"


def test_convert_image_resizes_with_aspect_ratio(tmp_path: Path):
    source = tmp_path / "source.png"
    source.write_bytes(image_bytes(size=(400, 200)))
    output = tmp_path / "out.webp"

    result = convert_image(source, output, "webp", width=100, height=100, keep_aspect=True)

    assert (result.width, result.height) == (100, 50)
    with Image.open(output) as converted:
        assert converted.size == (100, 50)


def test_convert_image_resizes_exactly_without_aspect_ratio(tmp_path: Path):
    source = tmp_path / "source.png"
    source.write_bytes(image_bytes(size=(400, 200)))
    output = tmp_path / "out.png"

    result = convert_image(source, output, "png", width=80, height=60, keep_aspect=False)

    assert (result.width, result.height) == (80, 60)


def test_convert_image_rejects_invalid_dimension(tmp_path: Path):
    source = tmp_path / "source.png"
    source.write_bytes(image_bytes())
    with pytest.raises(ImageConverterError) as error:
        convert_image(source, tmp_path / "out.png", "png", width=50_000)
    assert error.value.code == "INVALID_DIMENSION"


def test_convert_image_preserves_metadata_without_reintroducing_orientation(tmp_path: Path):
    source = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "WebNAS"
    Image.new("RGB", (40, 20), (30, 80, 140)).save(source, "JPEG", exif=exif)
    output = tmp_path / "out.jpg"

    result = convert_image(source, output, "jpeg", 90, strip_metadata=False)

    assert (result.width, result.height) == (20, 40)
    with Image.open(output) as converted:
        converted_exif = converted.getexif()
        assert converted.size == (20, 40)
        assert converted_exif.get(274) is None
        assert converted_exif.get(315) == "WebNAS"


def test_directory_conversion_preserves_subdirectories_and_avoids_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "photos"
    nested = source / "trip"
    nested.mkdir(parents=True)
    (source / "one.png").write_bytes(image_bytes())
    (nested / "two.png").write_bytes(image_bytes())
    output = tmp_path / "converted"
    output.mkdir()
    (output / "one.webp").write_bytes(b"existing")

    monkeypatch.setattr(image_service_module, "resolve_user_path", lambda _username, requested: Path(requested))
    monkeypatch.setattr(image_service_module, "assert_write_allowed", lambda _path: None)
    service = ImageConverterService(temp_root=tmp_path / "temp")

    result = service.convert_directory("alice", str(source), str(output), "webp", 80, True)

    assert len(result["converted"]) == 2
    assert not result["failed"]
    assert (output / "one-1.webp").is_file()
    assert (output / "trip" / "two.webp").is_file()
    assert (output / "one.webp").read_bytes() == b"existing"


def test_directory_conversion_can_write_to_source_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "photos"
    source.mkdir()
    (source / "one.png").write_bytes(image_bytes())

    monkeypatch.setattr(image_service_module, "resolve_user_path", lambda _username, requested: Path(requested))
    monkeypatch.setattr(image_service_module, "assert_write_allowed", lambda _path: None)
    service = ImageConverterService(temp_root=tmp_path / "temp")

    result = service.convert_directory("alice", str(source), str(source), "jpeg", 90, False)

    assert len(result["converted"]) == 1
    assert (source / "one.jpg").is_file()


def test_directory_conversion_can_atomically_overwrite_source_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "photos"
    source.mkdir()
    original = source / "one.png"
    original.write_bytes(image_bytes(size=(64, 32)))

    monkeypatch.setattr(image_service_module, "resolve_user_path", lambda _username, requested: Path(requested))
    monkeypatch.setattr(image_service_module, "assert_write_allowed", lambda _path: None)
    service = ImageConverterService(temp_root=tmp_path / "temp")

    result = service.convert_directory("alice", str(source), str(source), "png", 90, False, width=32, overwrite_policy="overwrite")

    assert len(result["converted"]) == 1
    assert not result["failed"]
    with Image.open(original) as converted:
        assert converted.size == (32, 16)
        converted.verify()
    assert not list(source.glob(".*.tmp"))


def test_directory_conversion_supports_prefix_suffix_and_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "photos"
    output = tmp_path / "converted"
    source.mkdir()
    output.mkdir()
    (source / "one.png").write_bytes(image_bytes())
    existing = output / "web-one-small.webp"
    existing.write_bytes(b"existing")

    monkeypatch.setattr(image_service_module, "resolve_user_path", lambda _username, requested: Path(requested))
    monkeypatch.setattr(image_service_module, "assert_write_allowed", lambda _path: None)
    service = ImageConverterService(temp_root=tmp_path / "temp")

    result = service.convert_directory(
        "alice", str(source), str(output), "webp", 80, False,
        prefix="web-", suffix="-small", overwrite_policy="skip",
    )

    assert result["converted"] == []
    assert len(result["skipped"]) == 1
    assert result["summary"]["skipped_count"] == 1
    assert existing.read_bytes() == b"existing"


def test_directory_conversion_can_overwrite_existing_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "photos"
    output = tmp_path / "converted"
    source.mkdir()
    output.mkdir()
    (source / "one.png").write_bytes(image_bytes())
    existing = output / "one.webp"
    existing.write_bytes(b"old")

    monkeypatch.setattr(image_service_module, "resolve_user_path", lambda _username, requested: Path(requested))
    monkeypatch.setattr(image_service_module, "assert_write_allowed", lambda _path: None)
    service = ImageConverterService(temp_root=tmp_path / "temp")

    result = service.convert_directory("alice", str(source), str(output), "webp", 80, False, overwrite_policy="overwrite")

    assert len(result["converted"]) == 1
    assert existing.read_bytes() != b"old"


def test_browse_ignores_symlinks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "photos"
    outside = tmp_path / "outside.png"
    source.mkdir()
    outside.write_bytes(image_bytes())
    link = source / "linked.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available on this platform")

    monkeypatch.setattr(image_service_module, "resolve_user_path", lambda _username, requested: Path(requested or source))
    service = ImageConverterService(temp_root=tmp_path / "temp")

    result = service.browse("alice", str(source))

    assert result["images"] == []


def test_service_exposes_frontend_limits():
    service = ImageConverterService()

    limits = service.limits()

    assert limits["max_upload_files"] == 100
    assert limits["max_file_bytes"] == 50 * 1024 * 1024
    assert limits["max_batch_bytes"] == 500 * 1024 * 1024
    assert limits["max_dimension"] == 32_768


def test_formats_only_expose_available_encoders():
    service = ImageConverterService()

    formats = service.formats()

    assert formats
    Image.init()
    assert all(image_service_module.OUTPUT_FORMATS[item["id"]][0] in Image.SAVE for item in formats)


def test_temporary_batch_builds_zip_and_removes_inputs(tmp_path: Path):
    service = ImageConverterService(temp_root=tmp_path / "temp")
    batch_id = service.create_batch("alice")
    service.add_upload("alice", batch_id, "one.png", image_bytes(), 1)
    service.add_upload("alice", batch_id, "two.png", image_bytes(), 2)

    result = service.convert_batch("alice", batch_id, "png", 90, width=12, height=12, prefix="mini-")
    archive = service.archive("alice", batch_id)

    assert result["download_url"].endswith(batch_id)
    assert len(result["converted"]) == 2
    assert result["summary"]["converted_count"] == 2
    assert all(item["width"] <= 12 and item["height"] <= 12 for item in result["converted"])
    with zipfile.ZipFile(archive) as bundle:
        assert sorted(bundle.namelist()) == ["mini-one.png", "mini-two.png"]
    assert not (archive.parent / "input").exists()
    assert not (archive.parent / "output").exists()

    service.delete_batch("alice", batch_id)
    assert not archive.parent.exists()


def test_upload_filename_is_reduced_to_basename(tmp_path: Path):
    service = ImageConverterService(temp_root=tmp_path / "temp")
    batch_id = service.create_batch("alice")
    path = service.add_upload("alice", batch_id, "../../photo.png", image_bytes(), 1)
    assert path.name == "photo.png"
    assert path.parent.name == "input"
