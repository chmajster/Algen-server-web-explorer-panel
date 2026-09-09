from PIL import Image, features

print(f"Image Converter ready; Pillow={Image.__version__}; webp={features.check('webp')}; avif={features.check('avif')}")
