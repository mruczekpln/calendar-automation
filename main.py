import asyncio
from vulcan import Vulcan, Keystore, Account

async def main():
  client = await load_client()
  await client.select_student()

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