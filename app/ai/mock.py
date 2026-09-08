from typing import TypeVar

from pydantic import BaseModel

from app.schemas.ai import (
    ContentAngleBatch,
    ContentIntelligence,
    RepurposeBundle,
    RepurposedItem,
    ShortScript,
)
from app.schemas.production import ScriptGeneration
from app.schemas.publishing import PlatformAdaptationOutput
from app.schemas.video import EditPlan, VideoConceptBatch

OutputT = TypeVar("OutputT", bound=BaseModel)


class MockAIProvider:
    """Deterministic provider for local smoke tests and development."""

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[OutputT],
    ) -> OutputT:
        data: object
        if response_model is ScriptGeneration:
            current = user_prompt.partition("CURRENT_SCRIPT:\n")[2].partition(
                "\n\nUSER_INSTRUCTION"
            )[0]
            instruction = user_prompt.partition("USER_INSTRUCTION:\n")[2].partition("\n\n")[0]
            if current:
                if "BestWay" in instruction or "бест" in instruction.casefold():
                    content = current + "\nНапример, в BestWay backend изолирует приложение от 1С."
                elif "начал" in instruction.casefold() or "скуч" in instruction.casefold():
                    content = "Прямой запрос в 1С может сломать приложение за секунду.\n" + current
                elif "цен" in instruction.casefold():
                    content = "\n".join(
                        line for line in current.splitlines() if "цен" not in line.casefold()
                    )
                else:
                    content = current + "\n" + instruction.strip()
            else:
                content = (
                    "Приложение не должно напрямую зависеть от 1С.\n"
                    "Прямая связь делает мобильный клиент зависимым от структуры "
                    "и доступности 1С.\n"
                    "Backend со стабильным REST API проверяет данные, кэширует ответы "
                    "и гасит сбои.\n"
                    "Так приложение остаётся быстрым, а интеграция — управляемой."
                )
            data = {
                "content": content,
                "sections": [
                    {"id": f"section_{index}", "text": line, "order": index}
                    for index, line in enumerate(content.splitlines(), start=1)
                    if line.strip()
                ],
            }
        elif response_model is PlatformAdaptationOutput:
            if "TARGET_PLATFORM=telegram" in user_prompt:
                data = {
                    "title": "Почему приложение отправляло запрос дважды",
                    "caption": (
                        "Нашли причину двойного REST-запроса: повторный вызов был связан с "
                        "жизненным циклом экрана. Разбираем, где ставить защиту от дублей."
                    ),
                    "description": (
                        "При возврате на экран приложение повторяло запрос, а 1С создавала "
                        "дубли. В посте — технический контекст и вывод про идемпотентность."
                    ),
                    "hashtags": ["разработка", "REST", "идемпотентность"],
                    "call_to_action": "Проверьте повторные вызовы в lifecycle вашего экрана.",
                }
            elif "TARGET_PLATFORM=tiktok" in user_prompt:
                data = {
                    "title": "Откуда взялся второй запрос",
                    "caption": "Вернулся на экран — получил дубль в 1С. Вот где спрятался баг.",
                    "description": "Короткий разбор двойного REST-запроса.",
                    "hashtags": ["код", "баг", "REST"],
                    "call_to_action": "Сохрани, чтобы проверить свой lifecycle.",
                }
            else:
                data = {
                    "title": "Почему приложение дважды отправляло REST-запрос",
                    "caption": "",
                    "description": (
                        "Разбираем баг жизненного цикла экрана, из-за которого 1С получала "
                        "две одинаковые записи, и объясняем роль идемпотентности API."
                    ),
                    "hashtags": ["REST", "mobiledevelopment", "backend"],
                    "call_to_action": "Подпишитесь на инженерные разборы.",
                }
        elif response_model is ContentIntelligence:
            data = {
                "topic": "Дублирующиеся REST-запросы при возврате на экран",
                "summary": (
                    "Приложение повторно отправляло запрос при возврате пользователя на экран, "
                    "из-за чего 1С получала две одинаковые записи."
                ),
                "source_facts": [
                    "Команда два часа искала баг",
                    "Приложение повторно отправляло запрос при возврате на экран",
                    "1С получала две одинаковые записи",
                ],
                "key_points": [
                    "Повторная отправка запроса связана с жизненным циклом экрана",
                    "На стороне 1С возникали дубли записей",
                ],
                "interesting_details": ["Баг проявлялся при возврате пользователя на экран"],
                "ai_suggestions": ["Показать связь UI lifecycle и идемпотентности API"],
                "content_angles": [
                    "Разбор причины двойного запроса",
                    "Почему API должен быть идемпотентным",
                ],
                "content_pillars": ["case", "education"],
                "target_audiences": ["Мобильные разработчики", "Backend-разработчики"],
                "content_potential_score": 82,
                "why_it_is_interesting": "Конкретный инженерный баг с понятным уроком.",
                "recommended_formats": ["short_video", "telegram_post"],
                "requires_more_context": False,
                "questions_to_user": [],
                "content_type": "talking_head",
            }
        elif response_model is VideoConceptBatch:
            data = {
                "concepts": [
                    {
                        "title": "История поиска двойного запроса",
                        "hook": "Мы два часа искали этот баг",
                        "focus": "Последовательная история поиска причины и инженерный вывод",
                        "target_duration": 42,
                        "framing": "center_crop",
                        "pace": "medium",
                    },
                    {
                        "title": "Почему запрос отправляется дважды",
                        "hook": "Один экран — два одинаковых запроса",
                        "focus": "Практическое объяснение причины для разработчиков",
                        "target_duration": 35,
                        "framing": "fit_blur",
                        "pace": "fast",
                    },
                    {
                        "title": "Идемпотентность защищает от дублей",
                        "hook": "UI-баг не должен создавать две записи в 1С",
                        "focus": "Архитектурный вывод про безопасный backend API",
                        "target_duration": 38,
                        "framing": "center_crop",
                        "pace": "calm",
                    },
                ]
            }
        elif response_model is EditPlan:
            data = {
                "clips": [
                    {
                        "source_start": 0,
                        "source_end": 5.2,
                        "source_segment_ids": [0],
                        "purpose": "hook",
                    },
                    {
                        "source_start": 5.2,
                        "source_end": 12.5,
                        "source_segment_ids": [1],
                        "purpose": "main",
                    },
                ],
                "hook_text": "ДВА ОДИНАКОВЫХ ЗАПРОСА",
                "emphasis": [],
                "recommended_duration": 12.5,
                "reasoning_summary": "Цельный технический фрагмент без выдуманной речи.",
                "framing": "center_crop",
                "pace": "medium",
            }
        elif response_model is ContentAngleBatch:
            data = {
                "angles": [
                    {
                        "title": "Почему приложение не должно ходить напрямую в 1С",
                        "hook": "Прямое подключение приложения к 1С — это архитектурная ловушка.",
                        "angle": "Экспертный разбор через границы систем",
                        "description": "Объяснить роль backend-прослойки и стабильного API.",
                        "format": "short_video",
                        "estimated_duration": 45,
                        "content_pillar": "education",
                        "target_audience": "Владельцы продуктов и разработчики",
                        "score": 8.8,
                    },
                    {
                        "title": "Ошибка интеграции, которая ломает мобильное приложение",
                        "hook": "Хотите сделать приложение зависимым от каждого обновления 1С?",
                        "angle": "Провокация и разбор типичной ошибки",
                        "description": "Показать последствия прямой связи на конкретных сбоях.",
                        "format": "short_video",
                        "estimated_duration": 40,
                        "content_pillar": "opinion",
                        "target_audience": "Технические руководители",
                        "score": 8.5,
                    },
                    {
                        "title": "Как один обмен с 1С положил приложение",
                        "hook": "Всё работало — пока в 1С не поменяли одно поле.",
                        "angle": "История инцидента с выводом",
                        "description": (
                            "Рассказать историю поломки и показать безопасную архитектуру."
                        ),
                        "format": "short_video",
                        "estimated_duration": 55,
                        "content_pillar": "case",
                        "target_audience": "Бизнес и продуктовые команды",
                        "score": 9.0,
                    },
                ]
            }
        elif response_model is ShortScript:
            data = {
                "title": "Почему приложению нужен backend между ним и 1С",
                "hook": "Есть ошибка, которую я часто вижу в приложениях с 1С.",
                "script": (
                    "Есть ошибка, которую я часто вижу в приложениях с 1С: приложение ходит "
                    "в неё напрямую. Тогда любое изменение структуры или недоступность 1С ломает "
                    "клиент. Между ними нужен backend со стабильным API. Он проверяет данные, "
                    "кэширует ответы и изолирует приложение от внутренних изменений. Это не "
                    "лишний слой — это граница, которая сохраняет продукт рабочим."
                ),
                "scenes": [
                    {
                        "start_second": 0,
                        "end_second": 4,
                        "spoken_text": "Есть частая ошибка.",
                        "on_screen": "Схема App → 1С",
                    },
                    {
                        "start_second": 4,
                        "end_second": 25,
                        "spoken_text": "Прямая связь хрупкая.",
                        "on_screen": "Красные точки отказа",
                    },
                    {
                        "start_second": 25,
                        "end_second": 45,
                        "spoken_text": "Добавьте backend.",
                        "on_screen": "App → API → 1С",
                    },
                ],
                "caption": "Зачем отделять мобильное приложение от 1С стабильным API.",
                "description": "Короткий разбор безопасной интеграционной архитектуры.",
                "call_to_action": "Сохраните, если проектируете интеграцию с 1С.",
                "estimated_duration": 45,
            }
        elif response_model is RepurposeBundle:
            base = RepurposedItem(
                title="Приложение, backend и 1С",
                hook="Не связывайте приложение с 1С напрямую.",
                script="Стабильный API между приложением и 1С снижает связанность и риск отказа.",
                caption="Архитектура интеграции без хрупких связей.",
                description="Практический принцип интеграционной архитектуры.",
                call_to_action="Расскажите, как устроена интеграция у вас.",
                estimated_duration=35,
            )
            post = base.model_copy(
                update={
                    "title": "Почему мобильному приложению не стоит работать с 1С напрямую",
                    "script": (
                        "Прямая интеграция кажется коротким путём, но связывает релизы приложения "
                        "с внутренней структурой 1С. Backend даёт стабильный контракт, валидацию, "
                        "кэширование и контролируемую деградацию. Дополнительный слой здесь "
                        "окупается "
                        "предсказуемостью системы."
                    ),
                    "estimated_duration": None,
                }
            )
            data = RepurposeBundle(youtube_short=base, tiktok=base, telegram_post=post).model_dump()
        else:
            raise TypeError(f"Unsupported mock response: {response_model.__name__}")
        return response_model.model_validate(data)
