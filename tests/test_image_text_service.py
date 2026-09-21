import io
import unittest

from PIL import Image

from app.services.image_text_service import ImageTextError, ImageTextService


class FakeGeminiResponse:
    text = "第一段條碼: 123\n第二段條碼: ABC\n第三段條碼: 999"


class FakeGeminiModels:
    def __init__(self):
        self.last_request = None

    def generate_content(self, model, contents):
        self.last_request = {
            "model": model,
            "contents": contents,
        }
        return FakeGeminiResponse()


class FakeGeminiClient:
    def __init__(self):
        self.models = FakeGeminiModels()


def make_png_bytes(size=(32, 24)):
    image = Image.new("RGB", size, color="white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class ImageTextServiceTest(unittest.TestCase):
    def test_extract_text_uses_gemini_client(self):
        fake_client = FakeGeminiClient()
        service = ImageTextService(client=fake_client, model="gemini-test", max_size=1024)

        result = service.extract_text(make_png_bytes(), mime_type="image/png")

        self.assertIn("第一段條碼", result.text)
        self.assertEqual(result.model, "gemini-test")
        self.assertEqual(result.mime_type, "image/png")
        self.assertEqual(result.width, 32)
        self.assertEqual(result.height, 24)
        self.assertEqual(fake_client.models.last_request["model"], "gemini-test")

    def test_invalid_image_raises_clear_error(self):
        service = ImageTextService(client=FakeGeminiClient())

        with self.assertRaises(ImageTextError):
            service.extract_text(b"not an image")


if __name__ == "__main__":
    unittest.main()
