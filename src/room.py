import discord
import persistent
from enum import Enum
from dataclasses import dataclass
import ZODB, ZODB.FileStorage
from BTrees import OOBTree
import os
import logging
from utils import follow_up

@dataclass
class dRoomStatus:
    name: str
    color: discord.Color

class RoomStatus(Enum):
    OPEN = dRoomStatus("Open", discord.Color.green())
    ASK = dRoomStatus("Ask", discord.Color.yellow())
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

    async def set_room_channel(self, requestor: discord.Member, interaction: discord.Interaction):
        if all([role.permissions.manage_channels == False for role in requestor.roles]):
            raise PermissionError("You do not have permission to set room channels.")
        with self.db.transaction() as conn: 
            conn.root.room_channels[interaction.guild.id] = interaction.channel.id
   
    async def create_room(self, interaction: discord.Interaction, requestor: discord.Member, hotel: str, room_number: int):
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
            message = await room_channel_obj.send(f"{hotel}-{room_number} Status: {RoomStatus.OPEN.value.name} | Vibe: {RoomVibe.CHILL.value.name}")
            room = Room(requestor, hotel, room_number, message)

            conn.root.rooms[room_key] = room
        await follow_up(interaction, f"Room {hotel} {room_number} created successfully.", ephemeral=True)
    
    def get_person_room(self, conn, person: discord.Member, hotel: str = None, room_number: int = None):
        if hotel and room_number:
            room_key = f"{hotel}-{room_number}"
            room = conn.root.rooms.get(room_key, None)
            if room and room.person_in_room(person):
                return room
            return None
        rooms = [room for room in conn.root.rooms.values() if room.person_in_room(person)]
        if len(rooms) == 0:
            return None
        return rooms[0]
    
    async def add_person_to_room(self, person: discord.Member, interaction: discord.Interaction, hotel: str = None, room_number: int = None):
        with self.db.transaction() as conn:
            room = self.get_person_room(conn, interaction.user, hotel, room_number)
            if not room:
                raise ValueError("No valid room found.")
            await room.add_person(interaction, interaction.user)
            await follow_up(interaction, f"{person.name} added to room {room.hotel} {room.room_number} successfully.", ephemeral=True)
   
    async def update_room_status(self, interaction: discord.Interaction, status: RoomStatus, vibe: RoomVibe, hotel: str = None, room_number: int = None):
        with self.db.transaction() as conn:
            room = self.get_person_room(conn, interaction.user, hotel, room_number)
            if not room:
                raise PermissionError("You do not belong to a room.")
            await room.update_status(interaction, interaction.user, status, vibe)
            await follow_up(interaction, f"Room status updated to {status.value.name} and vibe to {vibe.value.name}.", ephemeral=True)

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
    status = RoomStatus.OPEN
    vibe = RoomVibe.CHILL

    def __init__(self, requestor: discord.Member, hotel: str, room_number: int, message: discord.Message):
        self.members = [requestor.id]
        self.message_id = message.id
        self.hotel = hotel
        self.room_number = room_number

    def person_in_room(self, person: discord.Member):
        return person.id in self.members

    async def add_person(self, context: discord.Interaction, person: discord.Member):
        if not context.user.id in self.members:
            raise PermissionError("You do not have permission to add people to this room.")
        # Add role to person
        if person.id in self.members:
            raise ValueError("Person is already in the room.")
        self.members.append(person.id)

    async def update_status(self, context: discord.Interaction, requestor: discord.Member, status: RoomStatus, vibe: RoomVibe):
        if requestor.id not in self.members:
            raise PermissionError("You are not a member of this room.")
        self.status = status
        self.vibe = vibe
        message = await context.channel.fetch_message(self.message_id)
        await message.edit(content=f"{self.hotel}-{self.room_number} Status: {self.status.value.name} | Vibe: {self.vibe.value.name}")
    
    async def cleanup(self, context: discord.Interaction):
        # Delete message
        message = await context.channel.fetch_message(self.message_id)
        await message.delete()