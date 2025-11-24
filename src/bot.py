from room import ConRoomManager, RoomStatus, RoomVibe
import os
import discord
from discord import app_commands
import dotenv
import logging
from utils import follow_up

logger = logging.getLogger('conbot')
logger.setLevel(logging.INFO)
env = dotenv.load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

def is_valid_name(name: str) -> bool:
        if len(name) < 3 or len(name) > 30:
            return False
        return all(c.isalnum() or c in ('_', '-') for c in name)


# Initialize command based bot. Should probably make most be ephemeral?
intents = discord.Intents.default()
intents.message_content = True

# Temporary guild ID
GUILD_ID = int(os.getenv("GUILD_ID"))
TEST_GUILD = discord.Object(id=GUILD_ID)

class ConBot(discord.Client):
    # Suppress error on the User attribute being None since it fills up later
    user: discord.ClientUser

    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        # A CommandTree is a special type that holds all the application command
        # state required to make it work. This is a separate class because it
        # allows all the extra state to be opt-in.
        # Whenever you want to work with application commands, your tree is used
        # to store and work with them.
        # Note: When using commands.Bot instead of discord.Client, the bot will
        # maintain its own tree instead.
        self.tree = app_commands.CommandTree(self)

    # In this basic example, we just synchronize the app commands to one guild.
    # Instead of specifying a guild to every command, we copy over our global commands instead.
    # By doing so, we don't have to wait up to an hour until they are shown to the end-user.
    async def setup_hook(self):
        # This copies the global commands over to your guild.
        self.tree.copy_global_to(guild=TEST_GUILD)
        await self.tree.sync(guild=TEST_GUILD)
bot = ConBot(intents=intents)

# Initialize managers
con_room_manager = ConRoomManager()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')

# Set room channel
@bot.tree.command(name="set_room_channel")
async def set_room_channel(interaction):
    if interaction.user.guild_permissions.manage_channels == False:
        await follow_up(interaction, "You do not have permission to set room channels.", ephemeral=True)
        return
    try:
        await con_room_manager.set_room_channel(interaction.user, interaction)
        await follow_up(interaction, "Room channel set successfully.", ephemeral=True)
    except Exception as e:
        await follow_up(interaction, str(e), ephemeral=True)
        raise e

# Create room
@bot.tree.command(name="create_room")
async def create_room(interaction, hotel: str, room_number: int):
    try:
        await con_room_manager.create_room(interaction, interaction.user, hotel, room_number)
    except Exception as e:
        await follow_up(interaction, str(e), ephemeral=True)
    
# Add person to room
@bot.tree.command(name="add_person_to_room")
async def add_person_to_room(interaction, person: discord.Member, hotel: str = None, room_number: int = None):
    try:
        await con_room_manager.add_person_to_room(person, interaction, hotel, room_number)
    except Exception as e:
        await follow_up(interaction, str(e), ephemeral=True)

# Update room status
@bot.tree.command(name="update_room_status")
async def update_room_status(interaction, status: RoomStatus, vibe: RoomVibe, hotel: str = None, room_number: int = None):
    try:
        await con_room_manager.update_room_status(interaction, status, vibe, hotel, room_number)
    except Exception as e:
        await follow_up(interaction, str(e), ephemeral=True)

# Remove room
@bot.tree.command(name="remove_room")
async def remove_room(interaction, hotel: str, room_number: int):
    try:
        await con_room_manager.remove_room(interaction, hotel, room_number)
        await follow_up(interaction, f"Room {hotel} {room_number} removed successfully.", ephemeral=True)
    except Exception as e:
        await follow_up(interaction, str(e), ephemeral=True)

bot.run(BOT_TOKEN)