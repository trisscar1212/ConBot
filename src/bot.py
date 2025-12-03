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

# Set admin role (Administrator only, hidden from general users)
@bot.tree.command(name="set_admin_role")
@app_commands.default_permissions(administrator=True)
async def set_admin_role(interaction, role: discord.Role):
    response_parts = []

    # Check permissions first
    if not interaction.user.guild_permissions.administrator:
        response_parts.append("❌ **Permission Denied**: You must have Administrator permission to set the admin role.")
    else:
        try:
            # Get the current admin role before setting the new one
            with con_room_manager.db.transaction() as conn:
                old_admin_role_id = con_room_manager.get_admin_role_id(interaction.guild.id, conn)

            old_role = None
            if old_admin_role_id:
                old_role = interaction.guild.get_role(old_admin_role_id)

            # Set the new admin role
            await con_room_manager.set_admin_role(interaction, role)

            # Success message
            if old_role:
                response_parts.append(f"✅ **Success**: Admin role updated from `{old_role.name}` to `{role.name}`.")
            else:
                response_parts.append(f"✅ **Success**: Admin role set to `{role.name}`.")
        except Exception as e:
            response_parts.append(f"❌ **Error**: {str(e)}")

    # Always show current admin role configuration
    try:
        with con_room_manager.db.transaction() as conn:
            current_admin_role_id = con_room_manager.get_admin_role_id(interaction.guild.id, conn)

        if current_admin_role_id:
            current_role = interaction.guild.get_role(current_admin_role_id)
            if current_role:
                response_parts.append(f"\n📋 **Current Admin Role**: {current_role.mention} (`{current_role.name}`)")
            else:
                response_parts.append(f"\n⚠️ **Current Admin Role**: Role ID `{current_admin_role_id}` (role not found)")
        else:
            response_parts.append("\n📋 **Current Admin Role**: None set")
    except Exception as e:
        response_parts.append(f"\n⚠️ Could not retrieve current admin role: {str(e)}")

    await follow_up(interaction, "\n".join(response_parts), ephemeral=True)

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
async def create_room(interaction, hotel: str, room_number: int, room_name: str = None):
    try:
        await con_room_manager.create_room(interaction, interaction.user, hotel, room_number, room_name)
    except Exception as e:
        await follow_up(interaction, str(e), ephemeral=True)
    
# Add person to room
@bot.tree.command(name="add_person_to_room")
async def add_person_to_room(interaction, person: discord.Member, hotel: str = None, room_number: int = None):
    try:
        await con_room_manager.add_person_to_room(person, interaction, hotel, room_number)
    except Exception as e:
        await follow_up(interaction, str(e), ephemeral=True)

# Autocomplete function for room names
async def room_name_autocomplete(interaction: discord.Interaction, current: str):
    try:
        with con_room_manager.db.transaction() as conn:
            # Get all rooms where the user is a member
            user_rooms = [room for room in conn.root.rooms.values() if room.person_in_room(interaction.user) and room.room_name]
            # Filter by current input and return up to 25 choices
            choices = [
                app_commands.Choice(name=room.room_name, value=room.room_name)
                for room in user_rooms
                if current.lower() in room.room_name.lower()
            ][:25]
            return choices
    except Exception:
        return []

# Update room status
@bot.tree.command(name="update_room_status")
@app_commands.autocomplete(room_name=room_name_autocomplete)
async def update_room_status(interaction, status: RoomStatus, vibe: RoomVibe, room_name: str = None, hotel: str = None, room_number: int = None):
    try:
        await con_room_manager.update_room_status(interaction, status, vibe, room_name, hotel, room_number)
    except Exception as e:
        await follow_up(interaction, str(e), ephemeral=True)

# Update room info (Admin only)
@bot.tree.command(name="update_room_info")
@app_commands.default_permissions(administrator=True)
async def update_room_info(interaction, old_hotel: str, old_room_number: int, new_hotel: str = None, new_room_number: int = None, new_room_name: str = None):
    try:
        await con_room_manager.update_room_info(interaction, old_hotel, old_room_number, new_hotel, new_room_number, new_room_name)
        changes = []
        if new_hotel:
            changes.append(f"hotel to '{new_hotel}'")
        if new_room_number:
            changes.append(f"room number to '{new_room_number}'")
        if new_room_name:
            changes.append(f"room name to '{new_room_name}'")
        changes_text = ", ".join(changes) if changes else "no changes"
        await follow_up(interaction, f"Room updated successfully. Changed: {changes_text}.", ephemeral=True)
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