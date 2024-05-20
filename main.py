from datetime import date, datetime, time, timedelta
import json
import asyncio
import yaml

from vulcan import Vulcan, Keystore, Account, data
from aiogoogle import Aiogoogle, GoogleAPI
from aiogoogle.auth.creds import UserCreds, ClientCreds, ApiKey

from typing import Literal

calendar_id = ""
TIMEZONE = "Europe/Warsaw"
TIMEZONE_OFFSET = "0" + str(datetime.now().astimezone().utcoffset())[0:4]

TODAY = date.today()
START = TODAY - timedelta(days=TODAY.weekday())
END = START + timedelta(days=4)

as_json = False


async def main() -> None:
    print(f"Creating/Updating lesson and exam events since {START} to {END}.\n")

    print("INIT: loading vulcan client")
    client = await load_vulcan_client()  # loading vulcan client
    await client.select_student()  # selecting main student

    # getting formatted lessons and exams
    print("VULCAN: fetching lessons data")
    formatted_lessons = await get_formatted_lessons(client, START, END, False)
    print("VULCAN: fetching exams data")
    formatted_exams = await get_formatted_exams(client)

    creds = get_aiogoocle_creds()  # getting aiogoogle credentials
    async with Aiogoogle(user_creds=creds[0], client_creds=creds[1]) as aiogoogle:  # opening async aiogoogle session
        print("AIOGOOGLE: creating Google Calendar API v3 service\n")
        calendar_service = await aiogoogle.discover("calendar", "v3")  # discovering calendar service api

        # await process_lessons(aiogoogle=aiogoogle, service=calendar_service, formatted_lessons=formatted_lessons)
        await process_exams(aiogoogle=aiogoogle, service=calendar_service, formatted_exams=formatted_exams)

    # closing http session
    await client.close()


async def load_vulcan_client() -> Vulcan:
    # loading keystore data
    with open("keystore.json", "r") as f:
        keystore = Keystore.load(f)

    # loading account data
    with open("account.json", "r") as f:
        account = Account.load(f)

    return Vulcan(keystore, account)


def get_aiogoocle_creds() -> tuple[UserCreds, ClientCreds]:
    with open("keys.yaml", "r") as stream:
        data = yaml.load(stream, Loader=yaml.FullLoader)

    user_creds = UserCreds(
        access_token=data["user_creds"]["access_token"],
        refresh_token=data["user_creds"]["refresh_token"],
        expires_at=data["user_creds"]["expires_at"],
    )

    client_creds = ClientCreds(
        client_id=data["client_creds"]["client_id"],
        client_secret=data["client_creds"]["client_secret"],
        scopes=data["client_creds"]["scopes"],
    )

    calendar_id = data["calendar_id"]

    return user_creds, client_creds


async def get_formatted_lessons(
    client: Vulcan, date_from: date, date_to: date, to_json: bool = False
) -> dict[date | str, list[dict[str, time | str]]]:
    # get lessons from the beggining of next week to end of the next week
    lessons_response = await client.data.get_lessons(date_from=date_from, date_to=date_to)

    lessons = {}
    moved_lessons = []

    day = []
    current_day = date_from
    async for lesson in lessons_response:
        if lesson.visible:
            if lesson.changes is None:
                data = {
                    "subject": lesson.subject.name,
                    "room": lesson.room.code,
                    "time_from": lesson.time.from_.isoformat() if to_json else lesson.time.from_,
                    "time_to": lesson.time.to.isoformat() if to_json else lesson.time.to,
                }

                if lesson.date.date == current_day:
                    day.append(data)
                else:
                    lessons[str(current_day) if to_json else current_day] = day
                    day = []

                    day.append(data)

                    current_day = lesson.date.date
            elif lesson.changes.type == 3:
                moved_lessons.append(lesson)

    if current_day == date_to:
        lessons[str(current_day) if to_json else current_day] = day

    CHANGED_START = date_from - timedelta(days=14)

    changed_lessons_response = await client.data.get_changed_lessons(date_from=CHANGED_START, date_to=date_to)
    changed_lessons = [
        lesson
        async for lesson in changed_lessons_response
        if lesson.changes.type != 1
        and (lesson.lesson_date.date > date_from or (lesson.change_date and lesson.change_date.date > date_from))
    ]

    # get changed lessons from 2 weeks before the beggining of next week to end of the next week
    for moved_lesson in moved_lessons:
        for changed_lesson in changed_lessons:
            if moved_lesson.changes.id == changed_lesson.id:
                data = {
                    "subject": moved_lesson.subject.name,
                    "room": moved_lesson.room.code,
                    "time_from": changed_lesson.time.from_.isoformat() if to_json else changed_lesson.time.from_,
                    "time_to": changed_lesson.time.to.isoformat() if to_json else changed_lesson.time.to,
                }

                moved_to_date = (
                    moved_lesson.date.date if changed_lesson.change_date is None else changed_lesson.change_date.date
                )
                moved_to_date = str(moved_to_date) if to_json else moved_to_date

                lessons[moved_to_date] = [data] + lessons[moved_to_date]

    # sort each nested lessons list
    for lesson in lessons:
        lessons[lesson] = sorted(lessons[lesson], key=lambda dict: dict["time_from"])

    return lessons


async def get_formatted_exams(
    client: Vulcan,
    last_sync: datetime = datetime.now() - timedelta(days=60),
    to_date: date = date.today() + timedelta(days=14),
    to_json: bool = False,
) -> list[dict[date | str, str]]:
    exams_response = await client.data.get_exams(last_sync=last_sync)

    exams = {}

    current_day = ""
    async for exam in exams_response:
        if exam.deadline.date > date.today() and exam.deadline.date < to_date:
            data = {"type": exam.type, "subject": exam.subject.name, "topic": exam.topic}
            current_day = str(exam.deadline.date) if to_json else exam.deadline.date

            if exams.get(current_day, False):
                exams[current_day] = [data] + exams[current_day]
            else:
                exams[current_day] = [data]

    return exams


def get_google_formatted_time(day: date, time_str: str) -> str:
    return datetime.fromisoformat(str(day) + f" {time_str}+{TIMEZONE_OFFSET}").isoformat()


def create_event_data(
    summary: str,
    date: date,
    description: str = "",
    time_from: time = None,
    time_to: time = None,
    type: str = "lesson",
) -> dict[str, str | dict[str, str]]:
    return (
        {
            "summary": summary,
            # "description": description,
            "start": {
                "dateTime": datetime.combine(date, time_from).isoformat(),
                "timeZone": TIMEZONE,
            },
            "end": {
                "dateTime": datetime.combine(date, time_to).isoformat(),
                "timeZone": TIMEZONE,
            },
            "reminders": {"useDefault": True},
        }
        if type == "lesson"
        else {
            "summary": summary,
            "description": description,
            "start": {
                "date": date.isoformat(),
            },
            "end": {
                "date": date.isoformat(),
            },
            "reminders": {"useDefault": True},
        }
    )


async def check_for_existing_events(aiogoogle: Aiogoogle, service: GoogleAPI, **kwargs) -> tuple[bool, list[int]]:
    list_events_response = await aiogoogle.as_user(service.events.list(calendarId=calendar_id, **kwargs))

    events = list_events_response.get("items", [])

    if len(events) == 0:
        return False, []
    else:
        return True, [event["id"] for event in events]


async def create_lesson_events(
    aiogoogle: Aiogoogle,
    service: GoogleAPI,
    day: date,
    lessons: list[dict[str, str | dict[str, str]]],
) -> None:
    for lesson in lessons:
        await aiogoogle.as_user(
            service.events.insert(
                calendarId=calendar_id,
                json=create_event_data(
                    summary=f"{lesson['subject']} - {lesson['room']}",
                    date=day,
                    time_from=lesson["time_from"],
                    time_to=lesson["time_to"],
                ),
            )
        )


async def create_exam_events(
    aiogoogle: Aiogoogle,
    service: GoogleAPI,
    day: date,
    exams: list[dict[str, str]],
) -> None:
    for exam in exams:
        await aiogoogle.as_user(
            service.events.insert(
                calendarId=calendar_id,
                json=create_event_data(
                    summary=f"{exam['type'].upper()} - {exam['subject']}",
                    date=day,
                    description=f"Temat: {exam['topic']}",
                    type="exam",
                ),
            )
        )


async def process_lessons(
    aiogoogle: Aiogoogle, service: GoogleAPI, formatted_lessons: dict[date | str, list[dict[str, time | str]]]
) -> None:
    for day, lessons in formatted_lessons.items():
        FIRST_TIMESLOT_START = get_google_formatted_time(day, "08:00")
        LAST_TIMESLOT_END = get_google_formatted_time(day, "15:45")

        existing, ids_to_delete = await check_for_existing_events(
            aiogoogle=aiogoogle,
            service=service,
            timeMin=FIRST_TIMESLOT_START,
            timeMax=LAST_TIMESLOT_END,
            orderBy="startTime",
            singleEvents=True,
        )

        if existing:
            print(str(day) + " lesson events exist, deleting and updating events.")

            for id in ids_to_delete:
                await aiogoogle.as_user(service.events.delete(calendarId=calendar_id, eventId=id))

            await create_lesson_events(aiogoogle=aiogoogle, service=service, day=day, lessons=lessons)

        else:
            print(str(day) + " is empty, creating lesson events.")

            await create_lesson_events(aiogoogle=aiogoogle, service=service, day=day, lessons=lessons)


async def process_exams(
    aiogoogle: Aiogoogle, service: GoogleAPI, formatted_exams: dict[date | str, list[dict[str, str]]]
) -> None:
    for day, exams in formatted_exams.items():
        DAY_START = get_google_formatted_time(day, "00:00")
        DAY_END = get_google_formatted_time(day + timedelta(days=1), "00:00")

        existing, ids_to_delete = await check_for_existing_events(
            aiogoogle=aiogoogle,
            service=service,
            timeMin=DAY_START,
            timeMax=DAY_END,
            q="Temat: ",
        )

        if existing:
            print(str(day) + " exam events exist, deleting and updating exam events.")
            print(ids_to_delete)

            for id in ids_to_delete:
                await aiogoogle.as_user(service.events.delete(calendarId=calendar_id, eventId=id))

            await create_exam_events(aiogoogle=aiogoogle, service=service, day=day, exams=exams)
        else:
            print(str(day) + " is empty, creating exam events.")

            await create_exam_events(aiogoogle=aiogoogle, service=service, day=day, exams=exams)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
