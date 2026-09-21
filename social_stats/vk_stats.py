import os
import sys
from datetime import date, datetime

import requests


class VKStats:
    def __init__(self, vk_api_key: str, group_id: str):
        self.vk_api_key = vk_api_key
        self.group_id = group_id

    def get_group_id(self) -> int:
        url = "https://api.vk.com/method/groups.getById"
        params = {
            "access_token": self.vk_api_key,
            "v": "5.236",
            "group_id": self.group_id,
        }
        response = requests.get(url, params=params).json()

        # Если VK вернул ошибку – показываем её явно
        if "error" in response:
            raise Exception(f"VK API error in groups.getById: {response['error']['error_msg']}")

        return response["response"][0]["id"]

    def get_stats(self, start_date: str, end_date: str):
        """
        Получить «сырую» статистику по группе за период.

        start_date, end_date — строки в формате 'YYYY-MM-DD'.
        Используем timestamp_from/timestamp_to, как в твоём примере.
        """
        url = "https://api.vk.com/method/stats.get"

        # Используем наивные datetime в локальном времени — VK принимает unix‑timestamp без таймзоны
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        params = {
            "access_token": self.vk_api_key,
            "v": "5.236",
            "group_id": self.group_id,
            "timestamp_from": int(start_dt.timestamp()),
            "timestamp_to": int(end_dt.timestamp()),
        }

        response = requests.get(url, params=params).json()

        if "error" in response:
            raise Exception(f"VK API error: {response['error']['error_msg']}")

        # VK возвращает список дней; работаем со всем списком, а не только с нулевым элементом
        return response.get("response", [])

    def display_aggregated_stats(self, stats):
        """
        Агрегированный вывод по периоду:
        возраст, пол, города, страны, подписчики, лайки.
        """
        total_likes = 0
        total_subscribers_delta = 0

        age_dist: dict[str, int] = {}
        sex_dist: dict[str, int] = {}
        cities_dist: dict[str, int] = {}
        countries_dist: dict[str, int] = {}

        for day_stats in stats:
            visitors_block = day_stats.get("visitors", {}) or {}

            # Лайки и подписчики за день
            total_likes += day_stats.get("likes", 0)
            total_subscribers_delta += day_stats.get("subscribed", 0) - day_stats.get(
                "unsubscribed", 0
            )

            # Возраст
            for item in visitors_block.get("age", []):
                age = item.get("value")
                cnt = item.get("count", 0)
                if age:
                    age_dist[age] = age_dist.get(age, 0) + cnt

            # Пол
            for item in visitors_block.get("sex", []):
                sex = item.get("value")  # 'm' / 'f'
                cnt = item.get("count", 0)
                if sex:
                    sex_dist[sex] = sex_dist.get(sex, 0) + cnt

            # Города
            for item in visitors_block.get("cities", []):
                name = item.get("name")
                cnt = item.get("count", 0)
                if name:
                    cities_dist[name] = cities_dist.get(name, 0) + cnt

            # Страны
            for item in visitors_block.get("countries", []):
                name = item.get("name")
                cnt = item.get("count", 0)
                if name:
                    countries_dist[name] = countries_dist.get(name, 0) + cnt

        print("=" * 60)
        print("Сводная статистика за период")
        print("=" * 60)

        print("\nЛАЙКИ И ПОДПИСЧИКИ:")
        print(f"  Всего лайков: {total_likes}")
        print(f"  Изменение подписчиков (подписались - отписались): {total_subscribers_delta}")

        print("\nВОЗРАСТ:")
        for age, cnt in sorted(age_dist.items(), key=lambda x: x[0]):
            print(f"  {age}: {cnt}")

        print("\nПОЛ:")
        sex_labels = {"m": "Мужчины", "f": "Женщины"}
        for sex, cnt in sex_dist.items():
            print(f"  {sex_labels.get(sex, sex)}: {cnt}")

        print("\nГОРОДА (топ 10):")
        for name, cnt in sorted(cities_dist.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {name}: {cnt}")

        print("\nСТРАНЫ:")
        for name, cnt in sorted(countries_dist.items(), key=lambda x: x[1], reverse=True):
            print(f"  {name}: {cnt}")

    def display_daily_stats(self, stats):
        """
        Построчный вывод по каждому дню:
        Дата | Просмотры | Посетители | Лайки | Репосты | Комментарии | Подписчики
        """
        print("Дата\t\tПросмотры\tПосетители\tЛайки\tРепосты\tКомментарии\tПодписчики")
        for day_stats in stats:
            visitors_block = day_stats.get("visitors", {}) or {}

            # Дата (unixtime или строка)
            ts = day_stats.get("day") or day_stats.get("period_from")
            if isinstance(ts, (int, float)):
                period = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            else:
                period = str(ts)

            views = visitors_block.get("views", day_stats.get("views", 0))
            visitors = visitors_block.get("visitors", 0)
            likes = day_stats.get("likes", 0)
            shares = day_stats.get("shares", 0)
            comments = day_stats.get("comments", 0)
            subscribers = day_stats.get("subscribed", 0) - day_stats.get("unsubscribed", 0)

            print(
                f"{period}\t{views}\t{visitors}\t{likes}\t{shares}\t{comments}\t{subscribers}"
            )



# Пример использования:
if __name__ == "__main__":
    # Добавляем корень проекта в PYTHONPATH, чтобы корректно импортировать config.py
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Реальные данные берём из config.py в корне проекта
    from config import vk_api_key, group_id

    # Пример: c 2025-11-25 по сегодня
    start_date = "2025-11-25"
    end_date = date.today().strftime("%Y-%m-%d")

    vk_stats = VKStats(vk_api_key, group_id)
    stats = vk_stats.get_stats(start_date, end_date)

    # Построчная статистика по дням
    vk_stats.display_daily_stats(stats)

    # Сводная статистика по периоду (возраст, пол, города, страны, лайки, подписчики)
    vk_stats.display_aggregated_stats(stats)