import requests


class VKPublisher:
    def __init__(self, vk_api_key, group_id):
        self.vk_api_key = vk_api_key
        self.group_id = group_id

    @staticmethod
    def _parse_json(response: requests.Response, method_name: str):
        """
        Аккуратно распарсить JSON‑ответ VK.
        Если VK вернул HTML/пустой ответ, поднимаем осмысленное исключение,
        вместо неочевидного "Expecting value: line 1 column 1 (char 0)".
        """
        try:
            data = response.json()
        except ValueError:
            text_snippet = response.text[:200].replace("\n", " ")
            raise Exception(
                f"VK API {method_name} вернул неверный JSON. "
                f"status={response.status_code}, body='{text_snippet}'"
            )

        return data

    def upload_photo(self, image_url):
        upload_resp = requests.get(
            url="https://api.vk.com/method/photos.getWallUploadServer",
            params={
                "access_token": self.vk_api_key,
                "v": "5.236",
                "group_id": self.group_id,
            },
        )
        upload_url_response = self._parse_json(upload_resp, "photos.getWallUploadServer")

        if "error" in upload_url_response:
            raise Exception(upload_url_response["error"]["error_msg"])

        upload_url = upload_url_response["response"]["upload_url"]
        image_data = requests.get(image_url).content
        upload_resp = requests.post(upload_url, files={"photo": ("image.jpg", image_data)})
        upload_response = self._parse_json(upload_resp, "photos.upload")

        save_resp = requests.get(
            url="https://api.vk.com/method/photos.saveWallPhoto",
            params={
                "access_token": self.vk_api_key,
                "v": "5.236",
                "group_id": self.group_id,
                "photo": upload_response["photo"],
                "server": upload_response["server"],
                "hash": upload_response["hash"],
            },
        )
        save_response = self._parse_json(save_resp, "photos.saveWallPhoto")

        photo_id = save_response["response"][0]["id"]
        owner_id = save_response["response"][0]["owner_id"]

        return f"photo{owner_id}_{photo_id}"

    def publish_post(self, content, image_url=None):
        # VK ограничивает длину текста поста (~4096 символов),
        # поэтому на всякий случай обрежем очень длинные сообщения.
        if len(content) > 4000:
            content = content[:4000]

        params = {
            "access_token": self.vk_api_key,
            "from_group": 1,
            "v": "5.236",
            "owner_id": f"-{self.group_id}",
            "message": content,
        }
        if image_url:
            attachment = self.upload_photo(image_url)
            params["attachments"] = attachment

        # Раньше мы передавали параметры через params=..., что делало ОЧЕНЬ длинный URL,
        # и VK возвращал 414 Request-URI Too Large. Теперь отправляем параметры в теле POST.
        resp = requests.post("https://api.vk.com/method/wall.post", data=params)
        response = self._parse_json(resp, "wall.post")
        return response