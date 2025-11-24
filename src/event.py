import discord
import persistent
import ZODB, ZODB.FileStorage
from BTrees import OOBTree
import os
import logging
from utils import is_valid_name

class ConEventManager:
    def __init__(self):
        db_exists = os.path.exists("events.fs")
        self.db = ZODB.DB(ZODB.FileStorage.FileStorage("events.fs"))
        if not db_exists:
            with self.db.transaction() as conn:
                conn.root.events = OOBTree.BTree()

    def event_manager(self, interaction: discord.Interaction):
        guild = interaction.guild
        owner = interaction.user
        if all([role.permissions.create_events == False for role in owner.roles]):
            raise PermissionError("You do not have permission to create events.")

    async def set_room_channel(self, requestor: discord.Member, interaction: discord.Interaction):
        if all([role.permissions.manage_channels == False for role in requestor.roles]):
            raise PermissionError("You do not have permission to set room channels.")
        with self.db.transaction() as conn: 
            conn.root.room_channels[interaction.guild.id] = interaction.channel.id

    async def create_event(self, interaction: discord.Interaction, role_name, channel_name):
        guild = interaction.guild
        owner = interaction.user
        if all([role.permissions.create_events == False for role in owner.roles]):
            raise PermissionError("You do not have permission to create events.")
        if not is_valid_name(role_name) or not is_valid_name(channel_name):
            raise ValueError("Role or channel name is invalid. Must be 3-30 characters long and contain only alphanumeric characters, underscores, or hyphens.")
        logging.info(f"Creating event {channel_name} with role {role_name} in guild {guild.name} ({guild.id}) by user {owner.name} ({owner.id})")
        event = Event(guild, owner)
        logging.info(f"Event object created for {channel_name}")
        logging.info("Setting up event...")
        await event.setup(guild, owner, role_name, channel_name)
        logging.info(f"Event {channel_name} setup complete.")
        with self.db.transaction() as conn:
            conn.root.events[event.text_channel_id] = event
        await interaction.response.send_message(f"Event '{channel_name}' created successfully.", ephemeral=True)

class Event(persistent.Persistent):
    # Creator of the event, can add more people
    owner_id = None
    role_id = None
    text_channel_id = None
    voice_channel_id = None
    guild_id = None
    
    def __init__(self, guild: discord.Guild, owner: discord.Member):
        self.owner_id = owner.id
        self.guild_id = guild.id

    async def setup(self, guild: discord.Guild, owner: discord.Member, role_name, channel_name):
        # Create role
        role = await guild.create_role(name=role_name)
        self.role_id = role.id
        # Assign admin the role
        await owner.add_roles(role)
        # Create the channel and assign it viewable to the role
        #TODO: Add sending to the right category?
        text_channel = await guild.create_text_channel(f"{channel_name}", overwrites={
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            role: discord.PermissionOverwrite(view_channel=True)
        })
        # voice channel is necessary to make "hidden" events :<
        voice_channel = await guild.create_voice_channel(f"{channel_name}-vc", overwrites={
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            role: discord.PermissionOverwrite(view_channel=True)
        })
        self.text_channel_id = text_channel.id
        self.voice_channel_id = voice_channel.id
        self.guild_id = guild.id

    async def add_person(self, context, person: discord.Member):
        # Add role to person
        role = context.guild.get_role(self.role_id)
        await person.add_roles(role)

    async def cleanup(self, context):
        # Delete role
        # Delete channel
        text_channel = context.guild.get_channel(self.text_channel_id)
        voice_channel = context.guild.get_channel(self.voice_channel_id)
        role = context.guild.get_role(self.role_id)
        await text_channel.delete()
        await voice_channel.delete()
        await role.delete()