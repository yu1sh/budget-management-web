"""Short home-page greetings, selected for the current local hour."""
from random import choice


MORNING_GREETINGS = (
    "おはようございます。",
    "おはようございます。今日もよい一日を。",
    "おはようございます。気持ちのよい朝になりますように。",
)
DAYTIME_GREETINGS = (
    "こんにちは。",
    "こんにちは。今日もおつかれさまです。",
    "こんにちは。穏やかな一日になりますように。",
)
EVENING_GREETINGS = (
    "こんばんは。",
    "こんばんは。今日も一日おつかれさまでした。",
    "こんばんは。ゆっくりお過ごしください。",
)


def greeting_for_hour(hour):
    if 5 <= hour < 11:
        greetings = MORNING_GREETINGS
    elif 11 <= hour < 18:
        greetings = DAYTIME_GREETINGS
    else:
        greetings = EVENING_GREETINGS
    return choice(greetings)
