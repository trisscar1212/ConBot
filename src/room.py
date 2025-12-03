import discord
import persistent
from enum import Enum
from dataclasses import dataclass
import ZODB, ZODB.FileStorage
from BTrees import OOBTree
import os
import logging
from datetime import datetime, timezone
from utils import follow_up

@dataclass
class dRoomStatus:
    name: str
    color: discord.Color

class RoomStatus(Enum):
    OPEN = dRoomStatus("Open", discord.Color.blue())
    ASK = dRoomStatus("Ask", discord.Color.orange())
    DND = dRoomStatus("Do Not Disturb", discord.Color.red())

class RoomVibe(Enum):
    OWO = dRoomStatus("OWO", discord.Color.blue())
    FLIRTY = dRoomStatus("Flirty", discord.Color.green())
    CHILL = dRoomStatus("Chill", discord.Color.yellow())
    EEPY = dRoomStatus("Eepy", discord.Color.red())

class ConRoomManager:
    def __init__(self):
        db_exists = os.path.exists("rooms.fs")
        self.db = ZODB.DB(ZODB.FileStorage.FileStorage("rooms.fs"))
        if not db_exists:
            with self.db.transaction() as conn:
                conn.root.rooms = OOBTree.BTree()
                conn.root.room_channels = OOBTree.BTree()
                conn.root.admin_roles = OOBTree.BTree()  # guild_id -> role_id

    def _ensure_admin_roles(self, conn):
        """Ensure admin_roles exists in the database (for existing databases)"""
        if not hasattr(conn.root, 'admin_roles'):
            conn.root.admin_roles = OOBTree.BTree()

    def has_admin_role(self, member: discord.Member, guild_id: int, conn) -> bool:
        """Check if a member has the admin role for room management"""
        self._ensure_admin_roles(conn)
        admin_role_id = conn.root.admin_roles.get(guild_id, None)
        if not admin_role_id:
            return False
        return any(role.id == admin_role_id for role in member.roles)

    def get_admin_role_id(self, guild_id: int, conn) -> int:
        """Get the admin role ID for a guild"""
        self._ensure_admin_roles(conn)
        return conn.root.admin_roles.get(guild_id, None)

    async def set_admin_role(self, interaction: discord.Interaction, role: discord.Role):
        """Set the admin role for room management (requires Administrator permission)"""
        if not interaction.user.guild_permissions.administrator:
            raise PermissionError("You must have Administrator permission to set the admin role.")
        with self.db.transaction() as conn:
            self._ensure_admin_roles(conn)
            conn.root.admin_roles[interaction.guild.id] = role.id

    async def set_room_channel(self, requestor: discord.Member, interaction: discord.Interaction):
        if all([role.permissions.manage_channels == False for role in requestor.roles]):
            raise PermissionError("You do not have permission to set room channels.")
        with self.db.transaction() as conn:
            conn.root.room_channels[interaction.guild.id] = interaction.channel.id
   
    async def create_room(self, interaction: discord.Interaction, requestor: discord.Member, hotel: str, room_number: int, room_name: str = None):
        if all([role.permissions.manage_channels == False for role in requestor.roles]):
            raise PermissionError("You do not have permission to create rooms.")
        room_key = f"{hotel}-{room_number}"
        with self.db.transaction() as conn:
            if room_key in conn.root.rooms:
                raise ValueError("Room already exists.")
            room_channel = conn.root.room_channels.get(interaction.guild.id, None)
            if not room_channel:
                raise ValueError("No room channel set for this server. Please set a room channel first.")
            await follow_up(interaction, f"Creating room {hotel} {room_number}...", ephemeral=True)
            room_channel_obj = interaction.guild.get_channel(room_channel)

            # Create temporary room to generate embed
            temp_room = Room(requestor, hotel, room_number, None, room_name)
            embed = await temp_room.create_embed(interaction.guild)
            message = await room_channel_obj.send(embed=embed)

            # Now create the actual room with the message
            room = Room(requestor, hotel, room_number, message, room_name)

            conn.root.rooms[room_key] = room
        await follow_up(interaction, f"Room {hotel} {room_number} created successfully.", ephemeral=True)
    
    def get_person_room(self, conn, person: discord.Member, room_name: str = None, hotel: str = None, room_number: int = None, require_membership: bool = True):
        # Search by room name if provided
        if room_name:
            if require_membership:
                rooms = [room for room in conn.root.rooms.values() if room.room_name == room_name and room.person_in_room(person)]
            else:
                rooms = [room for room in conn.root.rooms.values() if room.room_name == room_name]
            if len(rooms) > 0:
                return rooms[0]
            return None
        # Search by hotel and room number if provided
        if hotel and room_number:
            room_key = f"{hotel}-{room_number}"
            room = conn.root.rooms.get(room_key, None)
            if room and (not require_membership or room.person_in_room(person)):
                return room
            return None
        # Otherwise find any room where person is a member
        if require_membership:
            rooms = [room for room in conn.root.rooms.values() if room.person_in_room(person)]
            if len(rooms) == 0:
                return None
            return rooms[0]
        return None
    
    async def add_person_to_room(self, person: discord.Member, interaction: discord.Interaction, hotel: str = None, room_number: int = None):
        with self.db.transaction() as conn:
            is_admin = self.has_admin_role(interaction.user, interaction.guild.id, conn)
            # Admins can add people to any room, regular users need membership
            room = self.get_person_room(conn, interaction.user, None, hotel, room_number, require_membership=not is_admin)
            if not room:
                raise ValueError("No valid room found.")
            await room.add_person(interaction, person, is_admin)
            await follow_up(interaction, f"{person.name} added to room {room.hotel} {room.room_number} successfully.", ephemeral=True)
   
    async def update_room_status(self, interaction: discord.Interaction, status: RoomStatus, vibe: RoomVibe, room_name: str = None, hotel: str = None, room_number: int = None):
        with self.db.transaction() as conn:
            is_admin = self.has_admin_role(interaction.user, interaction.guild.id, conn)
            # Admins can access any room, regular users need membership
            room = self.get_person_room(conn, interaction.user, room_name, hotel, room_number, require_membership=not is_admin)
            if not room:
                raise PermissionError("You do not belong to a room.")
            await room.update_status(interaction, interaction.user, status, vibe, is_admin)
            await follow_up(interaction, f"Room status updated to {status.value.name} and vibe to {vibe.value.name}.", ephemeral=True)

    async def update_room_info(self, interaction: discord.Interaction, old_hotel: str, old_room_number: int, new_hotel: str = None, new_room_number: int = None, new_room_name: str = None):
        """Update room information (admin only)"""
        with self.db.transaction() as conn:
            # Check admin permission
            if not self.has_admin_role(interaction.user, interaction.guild.id, conn):
                raise PermissionError("You must have the admin role to update room information.")

            # Get the room
            old_room_key = f"{old_hotel}-{old_room_number}"
            room = conn.root.rooms.get(old_room_key, None)
            if not room:
                raise ValueError("Room does not exist.")

            # Update room properties
            if new_hotel is not None:
                room.hotel = new_hotel
            if new_room_number is not None:
                room.room_number = new_room_number
            if new_room_name is not None:
                room.room_name = new_room_name

            room.last_updated = datetime.now(timezone.utc)

            # If hotel or room number changed, update the key in the database
            new_room_key = f"{room.hotel}-{room.room_number}"
            if old_room_key != new_room_key:
                del conn.root.rooms[old_room_key]
                conn.root.rooms[new_room_key] = room

            # Update the room card
            channel = interaction.guild.get_channel(room.channel_id)
            message = await channel.fetch_message(room.message_id)
            embed = await room.create_embed(interaction.guild)
            await message.edit(embed=embed)

    async def remove_room(self, interaction: discord.Interaction, hotel: str, room_number: int):
        room_key = f"{hotel}-{room_number}"
        with self.db.transaction() as conn:
            room = conn.root.rooms.get(room_key, None)
            if not room:
                raise ValueError("Room does not exist.")
            await room.cleanup(interaction)
            del conn.root.rooms[room_key]

class Room(persistent.Persistent):
    members = None
    message_id = None
    channel_id = None
    status = RoomStatus.OPEN
    vibe = RoomVibe.CHILL
    room_name = None
    last_updated = None

    def __init__(self, requestor: discord.Member, hotel: str, room_number: int, message: discord.Message = None, room_name: str = None):
        self.members = [requestor.id]
        self.message_id = message.id if message else None
        self.channel_id = message.channel.id if message else None
        self.hotel = hotel
        self.room_number = room_number
        self.room_name = room_name
        self.last_updated = datetime.now(timezone.utc)

    def person_in_room(self, person: discord.Member):
        return person.id in self.members

    def get_status_emoji(self):
        """Returns a colored emoji indicator based on room status"""
        if self.status == RoomStatus.OPEN:
            return "🟦"  # Blue square
        elif self.status == RoomStatus.ASK:
            return "🟧"  # Orange square
        elif self.status == RoomStatus.DND:
            return "🟥"  # Red square
        return "⬜"  # Default white square

    async def create_embed(self, guild: discord.Guild):
        """Creates a Discord embed card for the room"""
        # Use room name as title if provided, otherwise use hotel-room number
        if self.room_name:
            title = f"{self.get_status_emoji()} {self.room_name}"
        else:
            title = f"{self.get_status_emoji()} Room"

        embed = discord.Embed(
            title=title,
            color=self.status.value.color,
            timestamp=self.last_updated
        )

        # Add hotel-room number as a field in the body
        embed.add_field(name="Location", value=f"{self.hotel} - Room {self.room_number}", inline=False)

        embed.add_field(name="Status", value=self.status.value.name, inline=True)
        embed.add_field(name="Vibe", value=self.vibe.value.name, inline=True)

        # Get member names
        member_mentions = []
        for member_id in self.members:
            member = guild.get_member(member_id)
            if member:
                member_mentions.append(member.mention)
            else:
                member_mentions.append(f"<@{member_id}>")  # Fallback to mention format

        members_text = ", ".join(member_mentions) if member_mentions else "No members"
        # Use inline=True to make the card wider and take less vertical space
        embed.add_field(name="Members", value=members_text, inline=True)

        return embed

    async def add_person(self, context: discord.Interaction, person: discord.Member, is_admin: bool = False):
        if not is_admin and not context.user.id in self.members:
            raise PermissionError("You do not have permission to add people to this room.")
        # Add role to person
        if person.id in self.members:
            raise ValueError("Person is already in the room.")
        self.members.append(person.id)
        self.last_updated = datetime.now(timezone.utc)

        # Update the room card to show the new member
        channel = context.guild.get_channel(self.channel_id)
        message = await channel.fetch_message(self.message_id)
        embed = await self.create_embed(context.guild)
        await message.edit(embed=embed)

    async def update_status(self, context: discord.Interaction, requestor: discord.Member, status: RoomStatus, vibe: RoomVibe, is_admin: bool = False):
        if not is_admin and requestor.id not in self.members:
            raise PermissionError("You are not a member of this room.")
        self.status = status
        self.vibe = vibe
        self.last_updated = datetime.now(timezone.utc)
        channel = context.guild.get_channel(self.channel_id)
        message = await channel.fetch_message(self.message_id)
        embed = await self.create_embed(context.guild)
        await message.edit(embed=embed)
    
    async def cleanup(self, context: discord.Interaction):
        # Delete message
        channel = context.guild.get_channel(self.channel_id)
        message = await channel.fetch_message(self.message_id)
        await message.delete()