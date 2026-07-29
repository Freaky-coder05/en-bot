import os
import asyncio
import nest_asyncio
from pyrogram import Client, filters

# Allows Pyrogram to run inside Colab's existing event loop
nest_asyncio.apply()

API_ID = "21740783"        # Replace with your API ID (int)
API_HASH = "a5dc7fec8302615f5b441ec5e238cd46"    # Replace with your API Hash (str)
BOT_TOKEN = "6610201435:AAFRx71V0Hq8ciO5F_q9BB8s_I6CrvM8CPI"  # Replace with your Bot Token (str)

app = Client("gpu_encoder_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

async def encode_video_gpu(input_file, output_file, resolution):
    """
    Encodes video using Nvidia T4 GPU (hevc_nvenc) for small size and high quality.
    """
    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-c:v", "hevc_nvenc",      # Nvidia GPU H.265 Encoder
        "-preset", "p6",           # Slower preset for better compression efficiency
        "-tune", "hq",             # High Quality tuning
        "-rc", "vbr",              # Variable Bitrate
        "-cq", "26",               # Constant Quality (Lower = Better Quality. 24-28 is ideal for HEVC)
        "-spatial_aq", "1",        # Improves details in flat/textured areas
        "-temporal_aq", "1",       # Improves motion quality
        "-vf", f"scale=-2:{resolution}", # Scales height to resolution, keeps aspect ratio divisible by 2
        "-c:a", "aac", "-b:a", "128k",   # Audio codec and bitrate
        output_file
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    await process.communicate()
    return output_file

@app.on_message(filters.video | filters.document)
async def handle_video(client, message):
    if not message.video and not message.document.mime_type.startswith("video/"):
        return
        
    status_msg = await message.reply_text("📥 Downloading video to Colab...")
    file_path = await message.download()
    
    # Define the 3 qualities (Height in pixels)
    qualities = {
        "1080p": 1080,
        "720p": 720,
        "480p": 480
    }
    
    for quality_name, height in qualities.items():
        out_file = f"encoded_{quality_name}.mp4"
        
        await status_msg.edit_text(f"🚀 Encoding to {quality_name} (HEVC) using T4 GPU...")
        
        # Run the GPU FFmpeg process
        await encode_video_gpu(file_path, out_file, height)
        
        # Check if the file was created successfully
        if os.path.exists(out_file):
            await status_msg.edit_text(f"📤 Uploading {quality_name}...")
            await message.reply_video(
                video=out_file, 
                caption=f"**Quality:** {quality_name}\n**Codec:** H.265 (HEVC GPU)",
                supports_streaming=True
            )
            # Clean up the output file to save Colab disk space
            os.remove(out_file) 
        else:
            await message.reply_text(f"❌ Failed to encode {quality_name}.")
            
    # Clean up the original downloaded file
    if os.path.exists(file_path):
        os.remove(file_path)
        
    await status_msg.edit_text("✅ All 3 qualities encoded and uploaded successfully!")

print("🤖 Bot is starting... Send a video to the bot on Telegram!")
app.run()
