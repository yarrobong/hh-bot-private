from __future__ import annotations

import argparse
import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..ai.base import AIError
from ..api import ApiError, datatypes
from ..main import BaseNamespace, BaseOperation
from ..utils.date import parse_api_datetime
from ..utils.string import rand_text

if TYPE_CHECKING:
    from ..main import HHApplicantTool


try:
    import readline

    readline.add_history("/cancel ")
    readline.add_history("/ban")
    readline.set_history_length(10_000)
except ImportError:
    pass


logger = logging.getLogger(__package__)

class Namespace(BaseNamespace):
    reply_message: str
    max_pages: int
    only_invitations: bool
    dry_run: bool
    use_ai: bool
    system_prompt: str
    message_prompt: str
    period: int


class Operation(BaseOperation):
    """Ответ всем работодателям."""

    __aliases__ = ["reply-empls", "reply-chats", "reall"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--resume-id",
            help="Идентификатор резюме. Если не указан, то просматриваем чаты для всех резюме",
        )
        parser.add_argument(
            "-m",
            "--reply-message",
            "--reply",
            help="Отправить сообщение во все чаты. Если не передать сообщение, то нужно будет вводить его в интерактивном режиме.",  # noqa: E501
        )
        parser.add_argument(
            "--period",
            type=int,
            help="Игнорировать отклики, которые не обновлялись больше N дней",
        )
        parser.add_argument(
            "-p",
            "--max-pages",
            type=int,
            default=25,
            help="Максимальное количество страниц для проверки",
        )
        parser.add_argument(
            "-oi",
            "--only-invitations",
            help="Отвечать только на приглашения",
            default=False,
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--dry-run",
            "--dry",
            help="Не отправлять сообщения, а только выводить параметры запроса",
            default=False,
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--use-ai",
            "--ai",
            help="Использовать AI для автоматической генерации ответов",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "--system-prompt",
            "--ai-system",
            help="Системный промпт для AI",
            default="Ты — соискатель на HeadHunter. Отвечай вежливо и кратко.",
        )
        parser.add_argument(
            "--message-prompt",
            "--prompt",
            help="Промпт для генерации сообщения",
            default="Напиши короткий ответ работодателю на основе истории переписки.",
        )

    def run(self, tool: HHApplicantTool, args: Namespace) -> None:
        self.tool = tool
        self.api_client = tool.api_client
        self.resume_id = tool.first_resume_id()
        self.reply_message = args.reply_message or tool.config.get(
            "reply_message"
        )
        self.max_pages = args.max_pages
        self.dry_run = args.dry_run
        self.only_invitations = args.only_invitations

        self.message_prompt = args.message_prompt
        self.cover_letter_ai = (tool.get_cover_letter_ai(args.system_prompt) if args.use_ai else None)
        self.period = args.period

        logger.debug(f"{self.reply_message = }")
        self.reply_employers()

    def reply_employers(self):
        blacklist = set(self.tool.get_blacklisted())
        me: datatypes.User = self.tool.get_me()
        resumes = self.tool.get_resumes()
        resumes = (
            list(filter(lambda x: x["id"] == self.resume_id, resumes))
            if self.resume_id
            else resumes
        )
        resumes = list(
            filter(
                lambda resume: resume["status"]["id"] == "published", resumes
            )
        )
        self._reply_chats(user=me, resumes=resumes, blacklist=blacklist)

    @property
    def _bot_base(self) -> Path:
        return Path(os.environ.get("HH_BOT_BASE", "/opt/hh-bot"))

    @property
    def _ask_dir(self) -> Path:
        return self._bot_base / "state" / "ask_requests"

    @property
    def _answers_dir(self) -> Path:
        return self._bot_base / "state" / "human_answers"

    @staticmethod
    def _load_json(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _save_json(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _clean_ai_marker(text: str, marker: str) -> str:
        marker_pos = text.upper().find(marker)
        if marker_pos < 0:
            return ""
        text = text[marker_pos + len(marker):].strip()
        if text.startswith(":"):
            text = text[1:].strip()
        return text

    @staticmethod
    def _is_disabled_by_employer(ex: ApiError) -> bool:
        data = getattr(ex, "data", {}) or {}
        if ApiError.has_error_value("disabled_by_employer", data):
            return True
        return "disabled_by_employer" in str(ex)

    def _pending_answer_path(self, nid: str) -> Path:
        return self._answers_dir / f"{nid}.json"

    def _load_pending_draft(self, nid: str) -> tuple[Path, dict, str]:
        path = self._pending_answer_path(nid)
        answer = self._load_json(path)
        if answer.get("status") != "drafted":
            return path, answer, ""
        draft = str(answer.get("draft_message") or "").strip()
        if not draft:
            return path, answer, ""
        return path, answer, draft

    def _mark_answer(
        self,
        path: Path,
        answer: dict,
        status: str,
        **extra: str,
    ) -> None:
        if not answer:
            answer = {"nid": path.stem}
        answer["status"] = status
        answer["updated_at"] = datetime.now().isoformat(timespec="seconds")
        answer.update(extra)
        self._save_json(path, answer)

    def _save_ask_request(
        self,
        nid: str,
        vacancy: dict,
        employer: dict,
        ask_text: str,
        message_history: list[str],
    ) -> None:
        ask_text = ask_text.strip() or (
            "Нужно ваше решение по этому чату. "
            "Посмотри контекст и напиши, что ответить работодателю."
        )
        self._save_json(
            self._ask_dir / f"{nid}.json",
            {
                "nid": nid,
                "vacancy": vacancy.get("name") or "",
                "employer": employer.get("name") or "",
                "ask_text": ask_text,
                "history": "\n".join(message_history[-20:]),
                "status": "waiting",
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
        )

    def _prepare_ai_message(
        self,
        nid: str,
        vacancy: dict,
        employer: dict,
        send_message: str,
        message_history: list[str],
    ) -> str:
        send_message = str(send_message or "").strip()
        upper = send_message.upper()

        if upper == "__SKIP__" or upper.startswith("__SKIP__"):
            logger.debug("AI skipped chat %s", nid)
            return ""

        if "__ASK__" in upper:
            ask_text = self._clean_ai_marker(send_message, "__ASK__")
            self._save_ask_request(
                nid=nid,
                vacancy=vacancy,
                employer=employer,
                ask_text=ask_text,
                message_history=message_history,
            )
            logger.debug("AI saved ask request for chat %s", nid)
            return ""

        return send_message

    def _send_message(
        self,
        nid: str,
        vacancy: dict,
        send_message: str,
        answer_path: Path | None = None,
        answer_data: dict | None = None,
    ) -> bool:
        if self.dry_run:
            logger.debug(
                "dry-run: отклик на %s: %s",
                vacancy.get("alternate_url"),
                send_message,
            )
            return True

        try:
            self.api_client.post(
                f"/negotiations/{nid}/messages",
                message=send_message,
                delay=random.uniform(1, 3),
            )
        except ApiError as ex:
            if answer_path and self._is_disabled_by_employer(ex):
                self._mark_answer(
                    answer_path,
                    answer_data or {},
                    "disabled_by_employer",
                    send_error=str(ex),
                )
            raise

        if answer_path:
            self._mark_answer(answer_path, answer_data or {}, "sent")
        print(f"📨 Отправлено для {vacancy['alternate_url']}")
        return True

    def _reply_chats(
        self,
        user: datatypes.User,
        resumes: list[datatypes.Resume],
        blacklist: set[str],
    ) -> None:
        resume_map = {r["id"]: r for r in resumes}

        base_placeholders = {
            "first_name": user.get("first_name") or "",
            "last_name": user.get("last_name") or "",
            "email": user.get("email") or "",
            "phone": user.get("phone") or "",
        }

        for negotiation in self.tool.get_negotiations(max_pages=self.max_pages):
            try:
                # try:
                #     self.tool.storage.negotiations.save(negotiation)
                # except RepositoryError as e:
                #     logger.exception(e)

                if not (resume := resume_map.get(negotiation["resume"]["id"])):
                    continue

                updated_at = parse_api_datetime(negotiation["updated_at"])

                # Пропуск откликов, которые не обновлялись более N дней (при просмотре они обновляются вроде)
                if (
                    self.period
                    and (datetime.now(updated_at.tzinfo) - updated_at).days
                    > self.period
                ):
                    continue

                state_id = negotiation["state"]["id"]
                if state_id == "discard":
                    continue

                if self.only_invitations and not state_id.startswith("inv"):
                    continue

                nid = negotiation["id"]
                vacancy = negotiation["vacancy"]
                employer = vacancy.get("employer") or {}
                salary = vacancy.get("salary") or {}

                if employer.get("id") in blacklist:
                    print(
                        "🚫 Пропускаем заблокированного работодателя",
                        employer.get("alternate_url"),
                    )
                    continue

                placeholders = {
                    "vacancy_name": vacancy.get("name", ""),
                    "employer_name": employer.get("name", ""),
                    "resume_title": resume.get("title") or "",
                    **base_placeholders,
                }

                logger.debug(
                    "Вакансия %(vacancy_name)s от %(employer_name)s"
                    % placeholders
                )

                page: int = 0
                last_message: datatypes.Message | None = None
                message_history: list[str] = []
                while True:
                    messages_res: datatypes.PaginatedItems[
                        datatypes.Message
                    ] = self.api_client.get(
                        f"/negotiations/{nid}/messages", page=page
                    )
                    if not messages_res["items"]:
                        break

                    last_message = messages_res["items"][-1]
                    for message in messages_res["items"]:
                        if not message.get("text"):
                            continue
                        author = (
                            "Работодатель"
                            if message["author"]["participant_type"]
                            == "employer"
                            else "Я"
                        )
                        message_date = parse_api_datetime(
                            message.get("created_at")
                        ).strftime("%d.%m.%Y %H:%M:%S")

                        message_history.append(
                            f"[ {message_date} ] {author}: {message['text']}"
                        )

                    if page + 1 >= messages_res["pages"]:
                        break
                    page += 1

                if not last_message:
                    continue

                is_employer_message = (
                    last_message["author"]["participant_type"] == "employer"
                )

                if is_employer_message or not negotiation.get(
                    "viewed_by_opponent"
                ):
                    answer_path, answer_data, draft_message = (
                        self._load_pending_draft(nid)
                    )
                    send_message = ""
                    if draft_message:
                        send_message = draft_message
                        logger.debug("Prepared human draft: %s", send_message)
                    elif self.reply_message:
                        send_message = (
                            rand_text(self.reply_message) % placeholders
                        )
                        logger.debug(f"Template message: {send_message}")
                    elif self.cover_letter_ai:
                        try:
                            ai_query = (
                                f"Вакансия: {placeholders['vacancy_name']}\n"
                                f"История переписки:\n"
                                + "\n".join(message_history[-10:])
                                + f"\n\nИнструкция: {self.message_prompt}"
                            )
                            send_message = self.cover_letter_ai.complete(
                                ai_query
                            )
                            send_message = self._prepare_ai_message(
                                nid=nid,
                                vacancy=vacancy,
                                employer=employer,
                                send_message=send_message,
                                message_history=message_history,
                            )
                            if not send_message:
                                continue
                            logger.debug(f"AI message: {send_message}")
                        except AIError as ex:
                            logger.warning(
                                f"Ошибка OpenAI для чата {nid}: {ex}"
                            )
                            continue
                    else:
                        print("🏢", placeholders["employer_name"])
                        print("💼", placeholders["vacancy_name"])
                        if salary:
                            print(
                                "💵 от",
                                salary.get("from") or salary.get("to") or 0,
                                "до",
                                salary.get("to") or salary.get("from") or 0,
                                salary.get("currency", "RUR"),
                            )

                        print("\nПоследние сообщения чата:")
                        print()
                        for msg in (
                            message_history[-5:]
                            if len(message_history) > 5
                            else message_history
                        ):
                            print(msg)

                        try:
                            print("-" * 40)
                            print("Активное резюме:", resume.get("title") or "")
                            print(
                                "/ban, /cancel необязательное сообщение для отмены"
                            )
                            send_message = input("Ваше сообщение: ").strip()
                        except EOFError:
                            continue

                        if not send_message:
                            print("🚶 Пропускаем чат")
                            continue

                        if send_message.startswith("/ban"):
                            self.api_client.put(
                                f"/employers/blacklisted/{employer['id']}"
                            )
                            blacklist.add(employer["id"])
                            print(
                                "🚫 Работодатель заблокирован",
                                employer.get("alternate_url"),
                            )
                            continue
                        elif send_message.startswith("/cancel"):
                            _, decline_msg = send_message.split("/cancel", 1)
                            self.api_client.delete(
                                f"/negotiations/active/{nid}",
                                with_decline_message=decline_msg.strip(),
                            )
                            print("❌ Отмена заявки", vacancy["alternate_url"])
                            continue

                    # Финальная отправка текста
                    self._send_message(
                        nid=nid,
                        vacancy=vacancy,
                        send_message=send_message,
                        answer_path=answer_path if draft_message else None,
                        answer_data=answer_data if draft_message else None,
                    )

            except ApiError as ex:
                logger.error(ex)

        print("📝 Сообщения разосланы!")
