from PIL import features

print(f"Image Converter activated; webp={features.check('webp')}; avif={features.check('avif')}")
