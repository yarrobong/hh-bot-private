#!/usr/bin/env python3
import json
import re
from datetime import datetime
from pathlib import Path
from text_style import humanize_outgoing_text

BASE = Path("/opt/hh-bot")
ASK_DIR = BASE / "state" / "ask_requests"
ANS_DIR = BASE / "state" / "human_answers"

TERMINAL_STATUSES = {
    "sent",
    "disabled_by_employer",
    "test_ignored",
    "ignored",
}

SAFE_TO_KEEP_STATUSES = {
    "drafted",
    "needs_review",
}

def load_json(path, default=None):
    if default is None:
        default = {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def clean(value):
    return " ".join(str(value or "").strip().split())

def low(value):
    return clean(value).lower()

def is_no(answer):
    a = low(answer)
    return (
        a in {"не", "нет", "неа", "no"}
        or "не хочу" in a
        or "не надо" in a
        or "не готов" in a
        or "не подходит" in a
        or "отказываюсь" in a
    )

def is_yes(answer):
    a = low(answer)
    return (
        a in {"да", "ага", "ок", "окей", "хорошо", "yes", "готов", "готова"}
        or "да, готов" in a
        or "готов пройти" in a
        or "готов ознакомиться" in a
        or "можно" in a
    )

def is_wait(answer):
    a = low(answer)
    return (
        a in {"жду", "хорошо жду", "ок жду", "буду ждать"}
        or "жду тогда" in a
        or "жду условия" in a
        or "жду тестовое" in a
    )

def is_unknown(answer):
    a = low(answer)
    return (
        "не знаю что" in a
        or "не даю что" in a
        or "не понимаю" in a
        or a in {"хз", "не знаю", "непонятно"}
    )

def has_external_action(ask_text):
    q = low(ask_text)
    triggers = [
        "telegram",
        "телеграм",
        "t.me",
        "перейдите по ссылке",
        "перейти по ссылке",
        "по ссылке",
        "зарегистрируйтесь",
        "зарегистрироваться",
        "заполните анкету",
        "заполнить анкету",
        "анкета",
        "напишите в",
        "напишите на почту",
        "почту",
        "email",
        "e-mail",
        "укажите телефон",
        "номер телефона",
        "паспорт",
        "снилс",
        "инн",
        "адрес",
        "карта",
    ]
    return any(x in q for x in triggers)

def has_test_or_interview(ask_text):
    q = low(ask_text)
    return any(x in q for x in [
        "тестовое",
        "тестовое задание",
        "тест",
        "интервью",
        "собеседование",
        "созвон",
        "встреч",
    ])

def has_schedule_conditions(ask_text):
    q = low(ask_text)
    return any(x in q for x in [
        "график",
        "смен",
        "ночн",
        "офис",
        "удален",
        "удалён",
        "гибрид",
        "зарплат",
        "оклад",
        "выход",
        "когда готовы",
        "дата выхода",
        "обучение",
        "курс",
        "стажировка",
    ])

def is_tools_question(ask_text):
    q = low(ask_text)
    return (
        "какими инструментами" in q
        and ("обращ" in q or "клиент" in q or "тикет" in q)
    )

def is_experience_question(ask_text):
    q = low(ask_text)
    return any(x in q for x in [
        "есть ли опыт",
        "какой опыт",
        "расскажите про опыт",
        "сколько опыта",
        "работали ли",
        "приходилось ли",
        "знакомы ли",
    ])

def is_salary_question(ask_text):
    q = low(ask_text)
    return any(x in q for x in [
        "зарплат",
        "ожидания",
        "оклад",
        "доход",
        "сколько хотите",
    ])

def is_format_question(ask_text):
    q = low(ask_text)
    return any(x in q for x in [
        "формат работы",
        "удален",
        "удалён",
        "офис",
        "гибрид",
        "екатеринбург",
        "москва",
        "санкт-петербург",
        "спб",
    ])

def risky_final_message(message):
    m = low(message)
    risky = [
        "__ask__",
        "__skip__",
        "паспорт",
        "снилс",
        "инн",
        "номер карты",
        "банковск",
        "адрес проживания",
        "я на месте",
        "сейчас позвоню",
        "перезвоню",
        "перейду по ссылке",
        "зарегистрируюсь",
        "пройду интервью в telegram",
        "напишу в telegram",
        "напишу в телеграм",
        "отправлю документы",
    ]
    return any(x in m for x in risky)

def make_needs_review(ans, reason):
    ans["status"] = "needs_review"
    ans["draft_message"] = ""
    ans["draft_error"] = reason
    ans["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return ans

def make_tools_answer(answer):
    a = clean(answer)

    if "битрикс" in low(a) or "bitrix" in low(a):
        return (
            "Здравствуйте! Из инструментов для работы с обращениями использовал Битрикс24. "
            "В нём можно фиксировать обращения, вести историю коммуникации, контролировать статус задачи "
            "и передавать информацию технической команде. Обычно сначала уточняю суть проблемы у клиента, "
            "фиксирую важные детали в обращении, затем при необходимости передаю задачу профильным специалистам "
            "и отслеживаю дальнейший статус."
        )

    return (
        "Здравствуйте! Из инструментов для работы с обращениями использовал: "
        + a
        + ". Обычно сначала уточняю суть проблемы у клиента, фиксирую детали обращения, "
          "затем при необходимости передаю задачу технической команде и отслеживаю дальнейший статус."
    )

def make_message(answer, ask_text, vacancy):
    answer = clean(answer)
    ask_text = clean(ask_text)
    vacancy = clean(vacancy)

    a = low(answer)
    q = low(ask_text)
    v = low(vacancy)

    if not answer:
        return None, "Пустой ответ. Нужно написать ответ в панели."

    if is_unknown(answer):
        return "Здравствуйте! Уточните, пожалуйста, о чём именно идёт речь?", None

    if "ошиб" in a and ("не подходит" in a or "не моё" in a or "не мое" in a):
        return "Здравствуйте! Извините, отклик был отправлен ошибочно. Эта вакансия мне не подходит.", None

    # Внешние действия не автоматизируем одной короткой фразой
    if has_external_action(ask_text):
        if is_no(answer):
            return (
                "Здравствуйте! Спасибо за информацию. Сейчас не готов переходить во внешние сервисы "
                "или проходить этап вне чата HH. Если возможно, давайте продолжим общение здесь."
            ), None

        return None, (
            "Работодатель просит внешнее действие: Telegram, ссылка, анкета, почта, телефон или документы. "
            "Автоматически такой ответ не отправляю. В панели напиши полный текст, который точно можно отправить работодателю."
        )

    # Тестовые / интервью
    if has_test_or_interview(ask_text):
        if is_wait(answer):
            return "Здравствуйте! Хорошо, жду условия тестового задания или дальнейшие инструкции здесь, в чате HH.", None

        if is_yes(answer):
            return "Здравствуйте! Да, готов ознакомиться с тестовым заданием или дальнейшими этапами отбора. Можете прислать детали здесь, в чате HH.", None

        if is_no(answer):
            return "Здравствуйте! Спасибо за информацию. Сейчас не готов продолжать этот этап отбора.", None

    # График / условия / обучение
    if has_schedule_conditions(ask_text):
        if is_no(answer):
            return "Здравствуйте! Спасибо за информацию. Сейчас эти условия мне не подходят, поэтому продолжать этот этап не буду.", None

        if is_yes(answer):
            return "Здравствуйте! Да, в целом готов обсудить такие условия. Можем продолжить здесь, в чате HH.", None

        if is_wait(answer):
            return "Здравствуйте! Хорошо, жду подробности по условиям и дальнейшим этапам здесь, в чате HH.", None

    # Инструменты обращений / тикеты
    if is_tools_question(ask_text):
        if len(answer) < 3:
            return None, "Ответ про инструменты слишком короткий. Напиши хотя бы название инструмента."
        return make_tools_answer(answer), None

    # Зарплата
    if is_salary_question(ask_text):
        if re.search(r"\d", answer):
            return (
                "Здравствуйте! По зарплатным ожиданиям рассматриваю предложения от "
                + answer
                + ", но готов обсуждать итоговую сумму в зависимости от задач, формата работы и условий."
            ), None
        if is_yes(answer):
            return "Здравствуйте! Готов обсудить зарплатные ожидания в зависимости от задач, формата работы и условий.", None

    # Формат работы
    if is_format_question(ask_text):
        if "екат" in a or "офис" in a:
            return "Здравствуйте! Офисный или гибридный формат рассматриваю в Екатеринбурге. Также готов к удалённому формату работы.", None
        if "удален" in a or "удалён" in a:
            return "Здравствуйте! Да, удалённый формат работы мне подходит.", None
        if is_no(answer):
            return "Здравствуйте! Спасибо за уточнение. Такой формат работы мне сейчас не подходит.", None

    # Вопрос про опыт
    if is_experience_question(ask_text):
        if is_no(answer):
            return (
                "Здравствуйте! Не буду преувеличивать: такого опыта как основного коммерческого у меня нет. "
                "Мой основной опыт — Python, Django, SQL, Git, Linux, автоматизация процессов, CRM, боты и AI-инструменты. "
                "Если эта технология используется в задачах, готов разобраться и быстро включиться."
            ), None

        if len(answer) < 25:
            return None, (
                "Ответ про опыт слишком короткий. Чтобы не отправить ерунду, напиши подробнее: "
                "был ли опыт, где применялся, насколько уверенно."
            )

    # Отказ
    if is_no(answer):
        return "Здравствуйте! Спасибо за информацию. Сейчас не готов продолжать этот этап.", None

    # Ожидание
    if is_wait(answer):
        return "Здравствуйте! Хорошо, жду подробности или дальнейшие инструкции здесь, в чате HH.", None

    # Простое да
    if is_yes(answer):
        return "Здравствуйте! Да, готов обсудить детали. Можем продолжить здесь, в чате HH.", None

    # Уже нормальный текст
    if a.startswith(("здравствуйте", "добрый день", "добрый вечер", "спасибо")) and len(answer) >= 35:
        return answer, None

    # Слишком короткие ответы без понятного контекста не отправляем
    if len(answer) < 25:
        return None, (
            "Ответ слишком короткий и контекст не распознан. "
            "Чтобы не отправить тупую фразу, напиши полный текст ответа в панели."
        )

    return "Здравствуйте! " + answer[0].upper() + answer[1:], None

def main():
    ANS_DIR.mkdir(parents=True, exist_ok=True)

    processed = 0
    drafted = 0
    needs_review = 0

    for ans_path in sorted(ANS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        ans = load_json(ans_path)
        nid = str(ans.get("nid") or ans_path.stem)
        status = ans.get("status")

        if status in TERMINAL_STATUSES:
            continue

        ask_path = ASK_DIR / f"{nid}.json"
        ask = load_json(ask_path)

        vacancy = ask.get("vacancy") or ""
        ask_text = ask.get("ask_text") or ""
        answer = ans.get("answer") or ""

        # Уже готовые черновики не перезаписываем
        if status == "drafted" and ans.get("draft_message"):
            print("=" * 100)
            print("CHAT:", nid)
            print("VACANCY:", vacancy)
            print("STATUS: drafted already, not changing")
            print()
            print("FINAL MESSAGE:")
            print(ans.get("draft_message"))
            print()
            print("DRY RUN: not sent")
            continue

        # needs_review тоже не трогаем, пока пользователь не перепишет ответ через панель
        if status == "needs_review":
            print("=" * 100)
            print("CHAT:", nid)
            print("VACANCY:", vacancy)
            print("STATUS: needs_review")
            print("ERROR:", ans.get("draft_error"))
            print("ANSWER:", answer)
            continue

        if status != "new":
            continue

        processed += 1
        final, error = make_message(answer, ask_text, vacancy)

        print("=" * 100)
        print("CHAT:", nid)
        print("VACANCY:", vacancy)
        print("ASK:", ask_text)
        print("HUMAN:", answer)
        print()

        if error:
            ans = make_needs_review(ans, error)
            save_json(ans_path, ans)
            needs_review += 1

            print("NEEDS REVIEW:")
            print(error)
            print()
            print("DRY RUN: not sent")
            continue

        if not final:
            ans = make_needs_review(ans, "Не удалось подготовить безопасный ответ.")
            save_json(ans_path, ans)
            needs_review += 1

            print("NEEDS REVIEW:")
            print(ans["draft_error"])
            print()
            print("DRY RUN: not sent")
            continue

        final = humanize_outgoing_text(final)

        if risky_final_message(final):
            ans = make_needs_review(ans, "Черновик содержит рискованное обещание или личные данные. Нужно переписать вручную.")
            save_json(ans_path, ans)
            needs_review += 1

            print("NEEDS REVIEW:")
            print(ans["draft_error"])
            print()
            print("DRAFT WAS:")
            print(final)
            print()
            print("DRY RUN: not sent")
            continue

        ans["status"] = "drafted"
        ans["draft_message"] = final
        ans.pop("draft_error", None)
        ans["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_json(ans_path, ans)
        drafted += 1

        print("FINAL MESSAGE:")
        print(final)
        print()
        print("DRY RUN: not sent")

    print("=" * 100)
    print(f"SUMMARY: processed={processed}, drafted={drafted}, needs_review={needs_review}")

if __name__ == "__main__":
    main()
