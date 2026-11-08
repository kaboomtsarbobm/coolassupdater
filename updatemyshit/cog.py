import asyncio
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

GITHUB_USER = "kaboomtsarbobm"
EXTRA_TOML = Path("config/extra.toml")
STATE_FILE = Path("config/updatemyshit_state.json")
LOCATION_RE = re.compile(r"github\.com/([^/]+)/([^/@#\s]+?)(?:\.git)?(?:[@#]|$)")


def load_my_packages() -> list[tuple[str, str, str]]:
    """Returns (owner, repo, subdirectory fragment) for every package of mine in extra.toml"""
    if not EXTRA_TOML.exists():
        return []
    data = tomllib.loads(EXTRA_TOML.read_text(encoding="utf-8"))
    found = []
    for pkg in data.get("ballsdex", {}).get("packages", []):
        match = LOCATION_RE.search(pkg.get("location", ""))
        if match and match.group(1).lower() == GITHUB_USER.lower():
            fragment = pkg["location"].partition("#")[2]
            found.append((match.group(1), match.group(2), fragment))
    return found


async def _run(*cmd: str) -> tuple[bool, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    return proc.returncode == 0, out.decode(errors="replace")[-300:]


async def pip_install(spec: str) -> tuple[bool, str]:
    if shutil.which("uv"):
        return await _run("uv", "pip", "install", "--python", sys.executable, "--upgrade", spec)
    ok, _ = await _run(sys.executable, "-m", "pip", "--version")
    if not ok:
        ok, _ = await _run(sys.executable, "-m", "ensurepip", "--upgrade")
        if not ok:
            return False, "no pip or uv available in this container"
    return await _run(sys.executable, "-m", "pip", "install", "--upgrade", spec)


class UpdateView(discord.ui.View):
    def __init__(self, bot: "BallsDexBot"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="press me to update lmao XP", style=discord.ButtonStyle.primary)
    async def update(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.disabled = True
        await interaction.response.edit_message(view=self)

        packages = load_my_packages()
        if not packages:
            await interaction.followup.send(f"no packages from {GITHUB_USER} in extra.toml")
            return

        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
        lines = []
        updated = False
        async with aiohttp.ClientSession() as session:
            for owner, repo, fragment in packages:
                url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
                async with session.get(url) as resp:
                    if resp.status != 200:
                        lines.append(f"❌ **{repo}**: no release found")
                        continue
                    tag = (await resp.json())["tag_name"]

                if state.get(repo) == tag:
                    lines.append(f"✅ **{repo}** already on {tag}")
                    continue

                spec = f"git+https://github.com/{owner}/{repo}.git@{tag}"
                if fragment:
                    spec += f"#{fragment}"
                ok, output = await pip_install(spec)
                if ok:
                    state[repo] = tag
                    updated = True
                    lines.append(f"⬆️ **{repo}** updated to {tag}")
                else:
                    lines.append(f"❌ **{repo}** failed: ```{output}```")

        if updated:
            STATE_FILE.write_text(json.dumps(state, indent=2))
            lines.append("\nrestart the bot to load the new versions")
        await interaction.followup.send("\n".join(lines))


class UpdateMyShit(commands.Cog):
    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    @app_commands.command(name="updatemyshit", description="yeah")
    async def updatemyshit(self, interaction: discord.Interaction["BallsDexBot"]):
        await interaction.response.send_message(view=UpdateView(self.bot))
