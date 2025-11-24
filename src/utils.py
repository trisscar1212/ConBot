def is_valid_name(name: str) -> bool:
        if len(name) < 3 or len(name) > 30:
            return False
        return all(c.isalnum() or c in ('_', '-') for c in name)

async def follow_up(interaction, message: str, ephemeral: bool = True):
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(message, ephemeral=ephemeral)