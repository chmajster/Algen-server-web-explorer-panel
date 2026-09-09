from __future__ import annotations

import importlib
import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.modules.image_converter.service import ImageConverterError, ImageConverterService, convert_image

image_service_module = importlib.import_module("app.modules.image_converter.service")


def image_bytes(mode: str = "RGB", color=(120, 30, 200)) -> bytes:
    stream = io.BytesIO()
    Image.new(mode, (24, 16), color).save(stream, "PNG")
    return stream.getvalue()


def test_convert_image_flattens_alpha_for_jpeg(tmp_path: Path):
    source = tmp_path / "alpha.png"
    source.write_bytes(image_bytes("RGBA", (255, 0, 0, 80)))
    output = tmp_path / "converted.jpg"

    result = convert_image(source, output, "jpeg", 85)

    assert result.output == str(output)
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


def test_temporary_batch_builds_zip_and_removes_inputs(tmp_path: Path):
    service = ImageConverterService(temp_root=tmp_path / "temp")
    batch_id = service.create_batch("alice")
    service.add_upload("alice", batch_id, "one.png", image_bytes(), 1)
    service.add_upload("alice", batch_id, "two.png", image_bytes(), 2)

    result = service.convert_batch("alice", batch_id, "png", 90)
    archive = service.archive("alice", batch_id)

    assert result["download_url"].endswith(batch_id)
    assert len(result["converted"]) == 2
    with zipfile.ZipFile(archive) as bundle:
        assert sorted(bundle.namelist()) == ["one.png", "two.png"]
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
