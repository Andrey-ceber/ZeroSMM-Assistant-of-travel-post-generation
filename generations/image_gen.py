from openai import OpenAI
from pathlib import Path
import os


class ImageGenerator:
    def __init__(self, openai_key):
        # Создаем клиент с явным указанием api_key (без proxies для совместимости с PythonAnywhere)
        self.client = OpenAI(api_key=openai_key)

    # --- Внутренняя подготовка промпта для DALL·E ---

    def _build_prompt(self, base_prompt: str, style: str = "photo", variant: int | None = None) -> str:
        """
        Строит промпт для генерации изображений на основе нового шаблона.
        Меняет только строку с [ОБЪЕКТ / ПРОДУКТ / СЦЕНА], остальное остается как шаблон.
        """
        # Берём описание объекта/продукта/сцены из base_prompt
        short = (base_prompt or "").strip()
        if len(short) > 200:
            short = short[:200]
        
        # Если промпт пустой, используем дефолтное значение
        if not short:
            short = "industrial product or equipment"
        
        # Базовый шаблон промпта
        prompt_template = """Ultra-realistic photograph.

Real-world photography, not a render, not an illustration.

A real {object_description} in a natural real environment.
The subject is physically present in the scene, correctly scaled and grounded.
Materials, textures, proportions, and details are realistic and accurate.

Lighting:
Natural real-world lighting.
Correct light direction, soft realistic shadows, natural color temperature.
No dramatic or cinematic lighting.

Camera:
Shot on a professional DSLR or mirrorless camera.
35mm or 50mm lens.
Natural depth of field.
Slight photographic imperfections allowed.

Environment:
Real location, believable background, correct perspective.
Natural interaction between subject and environment (shadows, reflections, contact points).

STRICTLY FORBIDDEN:
NO 3D render
NO CGI
NO digital art
NO illustration
NO concept art
NO blueprint overlays
NO technical diagrams
NO isometric view
NO studio background
NO floating objects
NO unreal engine
NO octane render
NO stylized or cinematic look

This must look like a real photograph taken in the real world."""

        # Заменяем только часть с описанием объекта/продукта/сцены
        final_prompt = prompt_template.format(object_description=short)
        
        # Ограничиваем длину промпта
        if len(final_prompt) > 3900:
            final_prompt = final_prompt[:3900]

        return final_prompt

    def generate_image(self, prompt: str, style: str = "photo"):
        """Сгенерировать одно изображение и вернуть его URL (обратная совместимость)."""
        dalle_prompt = self._build_prompt(prompt, style=style, variant=0)

        # Для обычной генерации используем DALL-E 3 (gpt-image-1.5 требует параметр image)
        response = self.client.images.generate(
          model="dall-e-3",
          prompt=dalle_prompt,
          size="1024x1024",
          quality="standard",
          n=1,
        )

        image_url = response.data[0].url
        return image_url

    def generate_images(self, prompt: str, n: int = 4, style: str = "photo", travel: bool = False):
        """Сгенерировать несколько вариантов изображения и вернуть список URL.

        DALL·E 3 поддерживает только n=1 за вызов, поэтому делаем несколько отдельных запросов
        с небольшими вариациями композиции.
        Если travel=True, промпт используется как есть (уже готовый travel image_prompt из text_gen).
        """
        if n < 1:
            n = 1

        urls: list[str] = []
        for i in range(n):
            if travel:
                dalle_prompt = (prompt or "").strip()[:3900]
                if not dalle_prompt:
                    dalle_prompt = "High-quality travel photography, natural light, 35mm. No text, no letters, no watermark."
            else:
                dalle_prompt = self._build_prompt(prompt, style=style, variant=i)
            response = self.client.images.generate(
                model="dall-e-3",
                prompt=dalle_prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            if response.data:
                urls.append(response.data[0].url)

        return urls

    def generate_image_with_base(
        self, 
        prompt: str, 
        base_image_path: str, 
        style: str = "photo",
        expand_canvas: bool = True
    ):
        """
        Генерирует изображение используя базовое изображение для расширения canvas.
        
        Args:
            prompt: Текстовый промпт для генерации
            base_image_path: Путь к базовому изображению (локальный файл)
            style: Стиль изображения (photo, illustration, flat)
            expand_canvas: Если True, расширяет canvas вокруг базового изображения
        
        Returns:
            URL сгенерированного изображения
        """
        if not os.path.exists(base_image_path):
            raise FileNotFoundError(f"Базовое изображение не найдено: {base_image_path}")
        
        # Подготавливаем промпт
        dalle_prompt = self._build_prompt(prompt, style=style, variant=0)
        
        # Добавляем инструкцию по расширению canvas, если нужно
        if expand_canvas:
            expanded_prompt = f"Use the uploaded image as the base image. Expand the canvas around it. {dalle_prompt}"
        else:
            expanded_prompt = f"Use the uploaded image as reference. {dalle_prompt}"
        
        try:
            # Используем gpt-image-1.5 с базовым изображением
            image_file = open(base_image_path, "rb")
            try:
                response = self.client.images.generate(
                    model="gpt-image-1.5",
                    prompt=expanded_prompt,
                    image=image_file,
                    size="1536x1024",
                    n=1,
                )
                
                if response.data and len(response.data) > 0:
                    return response.data[0].url
                else:
                    raise ValueError("Пустой ответ от API генерации изображений")
            finally:
                image_file.close()
        except Exception as e:
            raise ValueError(f"Ошибка при генерации изображения с базовым изображением: {e}")

    def generate_images_with_base(
        self,
        prompt: str,
        base_image_path: str,
        n: int = 4,
        style: str = "photo",
        expand_canvas: bool = True
    ):
        """
        Генерирует несколько вариантов изображения используя базовое изображение.
        
        Args:
            prompt: Текстовый промпт для генерации
            base_image_path: Путь к базовому изображению (локальный файл)
            n: Количество вариантов для генерации
            style: Стиль изображения (photo, illustration, flat)
            expand_canvas: Если True, расширяет canvas вокруг базового изображения
        
        Returns:
            Список URL сгенерированных изображений
        """
        if n < 1:
            n = 1
        
        urls: list[str] = []
        for i in range(n):
            # Используем разные варианты промпта для разнообразия
            variant_prompt = self._build_prompt(prompt, style=style, variant=i)
            
            if expand_canvas:
                expanded_prompt = f"Use the uploaded image as the base image. Expand the canvas around it. {variant_prompt}"
            else:
                expanded_prompt = f"Use the uploaded image as reference. {variant_prompt}"
            
            try:
                # Открываем файл для каждого запроса
                image_file = open(base_image_path, "rb")
                try:
                    response = self.client.images.generate(
                        model="gpt-image-1.5",
                        prompt=expanded_prompt,
                        image=image_file,
                        size="1536x1024",
                        n=1,
                    )
                    
                    if response.data and len(response.data) > 0:
                        urls.append(response.data[0].url)
                finally:
                    image_file.close()
            except Exception as e:
                # Пропускаем ошибки для отдельных вариантов, но продолжаем
                print(f"Ошибка при генерации варианта {i+1}: {e}")
                continue
        
        return urls if urls else [self.generate_image_with_base(prompt, base_image_path, style, expand_canvas)]