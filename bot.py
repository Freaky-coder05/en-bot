import os
import shutil
import asyncio
from time import time
from math import floor
import nest_asyncio
from pyrogram import Client, filters

# ─── REQUIRED FOR GOOGLE COLAB ──────────────────────────────────────────
# Allows Pyrogram's asyncio loop to run inside Jupyter/Colab notebooks
nest_asyncio.apply()

# ─── CREDENTIALS ────────────────────────────────────────────────────────
API_ID = "21740783"        # Replace with your API ID (int)
API_HASH = "a5dc7fec8302615f5b441ec5e238cd46"    # Replace with your API Hash (str)
BOT_TOKEN = "6610201435:AAFRx71V0Hq8ciO5F_q9BB8s_I6CrvM8CPI"  # Replace with your Bot Token (str)

# Initialize Bot
app = Client(
    "anime_encoder_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ─── HELPER FUNCTIONS ───────────────────────────────────────────────────
async def _get_duration(file_path):
    """Gets the duration of the video in seconds using ffprobe."""
    cmd = (
        f'ffprobe -v error -show_entries format=duration '
        f'-of default=noprint_wrappers=1:nokey=1 "{file_path}"'
    )
    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0

async def _find_eng_sub_index(file_path):
    """Finds the stream index of the first English subtitle track."""
    cmd = (
        f'ffprobe -v error -select_streams s -show_entries stream=index:stream_tags=language '
        f'-of csv=p=0 "{file_path}"'
    )
    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    output = stdout.decode().strip().split('\n')
    
    # Defaults to the first subtitle track if specific 'eng' isn't found
    first_sub_idx = None
    for line in output:
        if not line: continue
        parts = line.split(',')
        idx = int(parts[0])
        if first_sub_idx is None:
            first_sub_idx = idx
        if len(parts) > 1 and 'eng' in parts[1].lower():
            return idx
    return first_sub_idx

async def _process_subtitle(raw_path, proc_path, skip_sec):
    """Basic subtitle processor (copies the raw SRT to the processed path for FFmpeg)."""
    if os.path.exists(raw_path):
        shutil.copy(raw_path, proc_path)
        return True
    return False

# ─── PROGRESS BAR HELPER ────────────────────────────────────────────────
async def pyrogram_progress(current, total, msg, action, start_time, last_update):
    """Updates Telegram messages with a progress bar."""
    now = time()
    if now - last_update[0] > 5 or current == total:
        last_update[0] = now
        percentage = current * 100 / total if total > 0 else 0
        
        filled = floor(percentage / 5)
        bar = "▓" * filled + "░" * (20 - filled)
        
        elapsed = now - start_time
        speed = current / elapsed if elapsed > 0 else 1
        est_time = (total - current) / speed if speed > 0 else 0
        
        text = (
            f"{action}\n\n"
            f"`[{bar}]` **{percentage:.1f}%**\n\n"
            f"📦 **Processed** : {current / (1024 * 1024):.1f} MB / {total / (1024 * 1024):.1f} MB\n"
            f"🚀 **Speed** : {speed / (1024 * 1024):.1f} MB/s\n"
            f"⏱ **ETA** : {int(est_time)} s"
        )
        try:
            await msg.edit(text)
        except Exception:
            pass

# ─── MAIN HANDLER ───────────────────────────────────────────────────────
@app.on_message(filters.video | filters.document)
async def handle_incoming_media(client, message):
    # Route incoming videos to the encoder function
    await quality_encode(client, message, c_thumb=None)

async def quality_encode(bot, query, c_thumb):
    UID         = query.from_user.id
    CHANNEL_TAG = "@Anime_warrior_tamil"
    BASE_TITLE  = "Demon Slayer infinity Castle- Movie 1-"
    SKIP_SEC    = 30

    ms = await query.reply_text("Pʟᴇᴀsᴇ Wᴀɪᴛ...\n\n**Fᴇᴛᴄʜɪɴɢ Qᴜᴇᴜᴇ 👥**")

    # ── one-at-a-time guard ──
    if os.path.isdir(f"ffmpeg/{UID}") and os.path.isdir(f"encode/{UID}"):
        return await ms.edit("**⚠️ Yᴏᴜ ᴄᴀɴ ᴄᴏᴍᴘʀᴇss ᴏɴʟʏ ᴏɴᴇ ғɪʟᴇ ᴀᴛ ᴀ ᴛɪᴍᴇ**")

    thumb_path = None
    Download_DIR = f"ffmpeg/{UID}"
    Output_DIR   = f"encode/{UID}"
    status_ms = None

    try:
        media = query
        file_obj = media.video or media.document
        if not file_obj:
            return await ms.edit("❌ **Send a valid video.**")

        filename = getattr(file_obj, "file_name", None) or f"video_{UID}.mp4"
        File_Path = f"{Download_DIR}/{filename}"

        os.makedirs(Download_DIR, exist_ok=True)
        os.makedirs(Output_DIR, exist_ok=True)

        try:
            start_time = time()
            last_update = [start_time]
            await bot.download_media(
                message=media,
                file_name=File_Path,
                progress=pyrogram_progress,
                progress_args=(ms, "📥 **Downloading File...**", start_time, last_update)
            )
            await ms.edit("File downloaded successfully ✅")
            await asyncio.sleep(2)
        except Exception as exc:
            return await ms.edit(f"❌ **Download failed:** `{exc}`")

        duration = await _get_duration(File_Path)

        sub_raw  = f"{Download_DIR}/sub_eng_raw.srt"
        sub_proc = f"{Download_DIR}/sub_eng_processed.srt"
        has_sub  = False

        status_ms = await query.reply_text("🔍 **Detecting English subtitle stream…**")
        eng_idx = await _find_eng_sub_index(File_Path)

        if eng_idx is not None:
            await status_ms.edit(f"✅ **Subtitle found (stream #{eng_idx}). Extracting…**")
            ep = await asyncio.create_subprocess_shell(
                f'ffmpeg -i "{File_Path}" -map 0:{eng_idx} -c:s srt "{sub_raw}" -y',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await ep.communicate()

            if os.path.exists(sub_raw) and os.path.getsize(sub_raw) > 50:
                has_sub = await _process_subtitle(sub_raw, sub_proc, skip_sec=SKIP_SEC)

        await status_ms.edit("✅ **Subtitle processed**" if has_sub else "⚠️ **No subtitle found**")
        await asyncio.sleep(2)

        original_bytes = os.path.getsize(File_Path)
        original_mb    = original_bytes / (1024 * 1024)

        RESOLUTIONS = {
            "480p":  {"w": 854,  "h": 480,  "cq": 28, "abr": "96k"},
            "720p":  {"w": 1280, "h": 720,  "cq": 26, "abr": "128k"},
            "1080p": {"w": 1920, "h": 1080, "cq": 24, "abr": "192k"},
        }

        EQ = "eq=contrast=1.00:saturation=0.70:gamma=0.95:brightness=-0.01"

        for res, cfg in RESOLUTIONS.items():
            w, h, cq, abr = cfg["w"], cfg["h"], cfg["cq"], cfg["abr"]
            vf = f"scale={w}:{h},{EQ}"
            full_title = f"{BASE_TITLE} {res} Tamil {CHANNEL_TAG}"
            out_filename = f"{full_title}.mkv"
            Output_Path = f"{Output_DIR}/{out_filename}"

            await status_ms.edit(f"🎬 **Starting {res} encode…**")

            meta = (
                f'-metadata title="{full_title}" '
                f'-metadata:s:v title="{CHANNEL_TAG}" '
                f'-metadata:s:a title="{CHANNEL_TAG}" '
            )
            if has_sub:
                meta += f'-metadata:s:s title="{CHANNEL_TAG}" -metadata:s:s language="eng" '
                inputs = f'-i "{File_Path}" -i "{sub_proc}"'
                map_flags = "-map 0:v:0 -map 0:a -map 1:s"
                sub_codec = "-c:s srt"
            else:
                inputs = f'-i "{File_Path}"'
                map_flags = "-map 0:v:0 -map 0:a"
                sub_codec = ""

            # T4 GPU HEVC Encoding Command
            cmd = (
                f'ffmpeg {inputs} {map_flags} '
                f'-c:v hevc_nvenc -preset p6 -tune hq -rc vbr -cq {cq} '
                f'-spatial_aq 1 -temporal_aq 1 -pix_fmt yuv420p '
                f'-vf "{vf}" '
                f'-c:a aac -b:a {abr} -ac 2 '
                f'{sub_codec} {meta} '
                f'-progress pipe:1 "{Output_Path}" -y'
            )

            process = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )

            stderr_chunks: list[str] = []
            async def _drain_stderr():
                while True:
                    line = await process.stderr.readline()
                    if not line: break
                    stderr_chunks.append(line.decode())
            drain_task = asyncio.create_task(_drain_stderr())

            last_upd = 0.0
            enc_start = time()
            
            while True:
                raw_line = await process.stdout.readline()
                if not raw_line: break
                line = raw_line.decode().strip()
                if "=" not in line: continue
                key, val = line.split("=", 1)
                if key != "out_time_us": continue
                
                try:
                    cur_t = int(val) / 1_000_000
                    percentage = min((cur_t / duration * 100), 100.0) if duration > 0 else 0.0
                    cur_mb = os.path.getsize(Output_Path) / (1024 * 1024) if os.path.exists(Output_Path) else 0.0
                    
                    if time() - last_upd > 5:
                        bar = "▓" * floor(percentage / 5) + "░" * (20 - floor(percentage / 5))
                        await status_ms.edit(
                            f"🎥 **Encoding [{res}]**\n\n"
                            f"`[{bar}]` **{percentage:.1f}%**\n\n"
                            f"⏱ **Elapsed** : {time() - enc_start:.0f} s\n"
                            f"📦 **Current** : {cur_mb:.1f} MB\n"
                            f"⚙️ **Codec** : hevc_nvenc (T4 GPU)"
                        )
                        last_upd = time()
                except (ValueError, ZeroDivisionError):
                    pass

            await process.wait()
            await drain_task

            if process.returncode != 0 or not os.path.exists(Output_Path) or os.path.getsize(Output_Path) == 0:
                err = "".join(stderr_chunks)[-1800:]
                await status_ms.edit(f"❌ **FFmpeg error [{res}]**\n```\n{err}\n```")
                continue

            final_mb = os.path.getsize(Output_Path) / (1024 * 1024)
            reduction = 100 - (final_mb / original_mb * 100) if original_mb else 0.0

            start_time = time()
            last_update = [start_time]

            await bot.send_document(
                UID,
                document=Output_Path,
                caption=(
                    f"🎥 **{full_title}**\n\n"
                    f"🎞 **Codec** : H.265 (HEVC NVENC)\n"
                    f"📁 **Original** : {original_mb:.1f} MB\n"
                    f"📦 **Encoded** : {final_mb:.1f} MB\n"
                    f"📉 **Reduction** : {reduction:.1f}%\n"
                    f"🔖 **Encoded by**: {CHANNEL_TAG}"
                ),
                force_document=True,
                progress=pyrogram_progress,
                progress_args=(status_ms, f"📤 **Uploading {res}...**", start_time, last_update)
            )
            
        if status_ms: await status_ms.delete()

    except Exception as exc:
        try: await ms.edit(f"❌ An error occurred:\n`{exc}`")
        except: pass
    finally:
        shutil.rmtree(Download_DIR, ignore_errors=True)
        shutil.rmtree(Output_DIR, ignore_errors=True)


# ─── START THE BOT ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 Bot is starting... Send a video to the bot on Telegram!")
    app.run()
