import asyncio
from vulcan import Vulcan, Keystore , Account, data


async def main():
  client = await load_client()
  await client.select_student()

  lessons = await client.data.get_lessons()
  async for lesson in lessons:
    print (lesson)
    # print(f"{changed_lesson.subject.name} w sali {changed_lesson.room.code} z {changed_lesson.teacher.name} {changed_lesson.teacher.surname}.")
  
  # changed_lessons = await client.data.get_changed_lessons()
  # async for changed_lesson in changed_lessons:
  #   print (changed_lesson)
  #   # print(f"Zmieniona {changed_lesson.subject.name}, notka: {changed_lesson.note}")

  # closing http session
  await client.close()

async def load_client():
  # loading keystore data
  with open ("keystore.json", 'r') as f:
    keystore = Keystore.load(f)

  # loading account data
  with open ("account.json", 'r') as f:
    account = Account.load(f)
  
  return Vulcan(keystore, account)

if __name__ == "__main__":
  loop = asyncio.get_event_loop()
  loop.run_until_complete(main())