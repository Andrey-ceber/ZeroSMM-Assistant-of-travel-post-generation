import requests


class TelegramPublisher:
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def publish_post(self, content, image_url=None):
        """
        Опубликовать пост в Telegram канал/чат.

        Args:
            content: Текст поста
            image_url: URL изображения (опционально)

        Returns:
            dict: Ответ от Telegram API
        """
        # Telegram ограничивает длину текста в одном сообщении (4096 символов),
        # поэтому на всякий случай обрежем очень длинные сообщения.
        if len(content) > 4000:
            content = content[:4000]

        if image_url:
            # Если есть изображение, отправляем через sendPhoto
            # Telegram ограничивает caption до 1024 символов
            caption = content[:1024] if len(content) > 1024 else content
            
            # Telegram может принять URL напрямую (если он публичный)
            # Но часто временные URL (например, от DALL-E) недоступны для Telegram,
            # поэтому сначала пробуем по URL, а если не получается - скачиваем и отправляем файлом
            try:
                response = requests.post(
                    f"{self.base_url}/sendPhoto",
                    data={
                        "chat_id": self.chat_id,
                        "photo": image_url,
                        "caption": caption,
                        "parse_mode": "HTML",  # для поддержки HTML-разметки в тексте
                    },
                    timeout=30,
                )
                # Проверяем ответ Telegram API на наличие ошибок
                try:
                    response_data = response.json()
                except ValueError:
                    raise Exception(f"Telegram API вернул не JSON. Status: {response.status_code}, Body: {response.text[:200]}")
                
                if not response_data.get('ok'):
                    error_info = response_data.get('error')
                    error_desc = 'Неизвестная ошибка'
                    error_code = 'unknown'
                    
                    if isinstance(error_info, dict):
                        error_desc = error_info.get('description', 'Неизвестная ошибка')
                        error_code = error_info.get('error_code', 'unknown')
                    elif isinstance(error_info, str):
                        error_desc = error_info
                    else:
                        # Если error не словарь и не строка, показываем весь ответ для отладки
                        import json
                        error_desc = f"Полный ответ: {json.dumps(response_data, ensure_ascii=False, indent=2)}"
                    
                    # Если ошибка связана с недоступностью URL, переходим к скачиванию файла
                    if 'wrong type of the web page content' in error_desc or 'Bad Request' in error_desc:
                        raise requests.exceptions.RequestException(f"URL недоступен для Telegram: {error_desc}")
                    
                    raise Exception(f"Telegram API вернул ошибку: {error_desc} (код: {error_code})")
                
                return response_data
            except (requests.exceptions.RequestException, Exception) as e:
                # Если не получилось отправить по URL (или URL недоступен), скачиваем и отправляем файлом
                try:
                    image_data = requests.get(image_url, timeout=30).content
                    # Обрезаем caption до 1024 символов
                    caption = content[:1024] if len(content) > 1024 else content
                    
                    response = requests.post(
                        f"{self.base_url}/sendPhoto",
                        data={"chat_id": self.chat_id, "caption": caption, "parse_mode": "HTML"},
                        files={"photo": ("image.jpg", image_data, "image/jpeg")},
                        timeout=30,
                    )
                    # Проверяем ответ Telegram API на наличие ошибок
                    try:
                        response_data = response.json()
                    except ValueError:
                        raise Exception(f"Telegram API вернул не JSON. Status: {response.status_code}, Body: {response.text[:200]}")
                    
                    if not response_data.get('ok'):
                        error_info = response_data.get('error', {})
                        error_desc = 'Неизвестная ошибка'
                        error_code = 'unknown'
                        
                        if isinstance(error_info, dict):
                            error_desc = error_info.get('description', 'Неизвестная ошибка')
                            error_code = error_info.get('error_code', 'unknown')
                        elif isinstance(error_info, str):
                            error_desc = error_info
                        else:
                            # Если error не словарь и не строка, показываем весь ответ
                            import json
                            error_desc = f"Полный ответ: {json.dumps(response_data, ensure_ascii=False, indent=2)}"
                        
                        raise Exception(f"Telegram API вернул ошибку: {error_desc} (код: {error_code})")
                    return response_data
                except requests.exceptions.RequestException as e2:
                    # Пытаемся извлечь детали ошибки из ответа Telegram
                    error_msg = str(e2)
                    try:
                        if hasattr(e2, 'response') and e2.response is not None:
                            try:
                                error_data = e2.response.json()
                                if 'description' in error_data.get('error', {}):
                                    error_msg = f"{error_data['error']['description']} (код: {error_data['error'].get('error_code', 'unknown')})"
                            except:
                                # Если не JSON, попробуем взять текст ответа
                                error_msg = f"{e2.response.status_code}: {e2.response.text[:200]}"
                    except:
                        pass
                    raise Exception(f"Ошибка отправки фото в Telegram: {error_msg}")
        else:
            # Если нет изображения, отправляем только текст через sendMessage
            try:
                response = requests.post(
                    f"{self.base_url}/sendMessage",
                    data={
                        "chat_id": self.chat_id,
                        "text": content,
                        "parse_mode": "HTML",
                    },
                    timeout=30,
                )
                # Проверяем ответ Telegram API на наличие ошибок
                try:
                    response_data = response.json()
                except ValueError:
                    raise Exception(f"Telegram API вернул не JSON. Status: {response.status_code}, Body: {response.text[:200]}")
                
                if not response_data.get('ok'):
                    error_info = response_data.get('error')
                    error_msg = "Неизвестная ошибка"
                    
                    if isinstance(error_info, dict):
                        error_desc = error_info.get('description', 'Неизвестная ошибка')
                        error_code = error_info.get('error_code', 'unknown')
                        error_msg = f"{error_desc} (код: {error_code})"
                    elif isinstance(error_info, str):
                        error_msg = error_info
                    else:
                        # Если error не словарь и не строка, показываем весь ответ для отладки
                        import json
                        error_msg = f"Полный ответ: {json.dumps(response_data, ensure_ascii=False, indent=2)}"
                    
                    raise Exception(f"Telegram API вернул ошибку: {error_msg}")
                return response_data
            except requests.exceptions.RequestException as e:
                # Пытаемся извлечь детали ошибки из ответа Telegram
                error_msg = str(e)
                try:
                    if hasattr(e, 'response') and e.response is not None:
                        try:
                            error_data = e.response.json()
                            if 'description' in error_data.get('error', {}):
                                error_msg = f"{error_data['error']['description']} (код: {error_data['error'].get('error_code', 'unknown')})"
                        except:
                            # Если не JSON, попробуем взять текст ответа
                            error_msg = f"{e.response.status_code}: {e.response.text[:200]}"
                except:
                    pass
                raise Exception(f"Ошибка отправки сообщения в Telegram: {error_msg}")

