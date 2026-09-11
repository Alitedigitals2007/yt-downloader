from flask import Flask, request, jsonify, send_file
import glob
import os
import shutil
import tempfile

import yt_dlp

app = Flask(__name__)

YOUTUBE_HOSTS = (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
)


def valid_url(value):
    if not value.startswith(("http://", "https://")):
        return False
    host = value.split("//", 1)[-1].split("/", 1)[0].split("?", 1)[0].lower()
    host = host.split(":", 1)[0]
    return any(host == h or host.endswith("." + h) for h in YOUTUBE_HOSTS)


def human_size(size):
    if not size:
        return None
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return None


def extract_info(url):
    base = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "no_color": True,
    }
    try:
        with yt_dlp.YoutubeDL(base) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception:
        fallback = dict(base)
        fallback["extractor_args"] = {"youtube": {"player_client": ["android", "web"]}}
        with yt_dlp.YoutubeDL(fallback) as ydl:
            return ydl.extract_info(url, download=False)


def build_video_entries(formats):
    entries = []
    for f in formats:
        if not f.get("url"):
            continue
        protocol = (f.get("protocol") or "").lower()
        if "m3u8" in protocol or "dash" in protocol or f.get("fragments"):
            continue
        has_video = f.get("vcodec") not in (None, "none")
        has_audio = f.get("acodec") not in (None, "none")
        if not has_video or not has_audio:
            continue
        height = f.get("height")
        label = f"{height}p" if height else (f.get("format_note") or "video")
        entries.append(
            {
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "label": label,
                "height": height or 0,
                "fps": f.get("fps"),
                "size": human_size(f.get("filesize") or f.get("filesize_approx")),
                "url": f["url"],
            }
        )
    entries.sort(key=lambda e: (e["height"], e["ext"] == "mp4"), reverse=True)
    seen = set()
    unique = []
    for e in entries:
        key = (e["height"], e["ext"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    return unique


def build_audio_entries(formats):
    entries = []
    for f in formats:
        if not f.get("url"):
            continue
        protocol = (f.get("protocol") or "").lower()
        if "m3u8" in protocol or "dash" in protocol or f.get("fragments"):
            continue
        has_video = f.get("vcodec") not in (None, "none")
        has_audio = f.get("acodec") not in (None, "none")
        if has_video or not has_audio:
            continue
        abr = f.get("abr")
        label = f"{int(abr)} kbps" if abr else (f.get("format_note") or "audio")
        entries.append(
            {
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "label": label,
                "abr": abr or 0,
                "acodec": f.get("acodec"),
                "size": human_size(f.get("filesize") or f.get("filesize_approx")),
                "url": f["url"],
            }
        )
    entries.sort(key=lambda e: e["abr"], reverse=True)
    seen = set()
    unique = []
    for e in entries:
        key = (e["ext"], e["label"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    return unique


@app.route("/api/formats", methods=["GET", "POST"])
def formats():
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        url = (payload.get("url") or "").strip()
    else:
        url = (request.args.get("url") or "").strip()

    if not url or not valid_url(url):
        return jsonify({"error": "Enter a valid YouTube link."}), 400

    try:
        info = extract_info(url)
    except Exception as exc:
        return jsonify({"error": f"Could not read this video: {exc}"}), 502

    all_formats = info.get("formats") or []
    video = build_video_entries(all_formats)
    audio = build_audio_entries(all_formats)

    if not video and not audio:
        return jsonify(
            {"error": "No direct download formats are available for this video."}
        ), 404

    return jsonify(
        {
            "title": info.get("title"),
            "uploader": info.get("uploader"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "webpage_url": info.get("webpage_url") or url,
            "video": video,
            "audio": audio,
        }
    )


def ffmpeg_path():
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def safe_name(title):
    cleaned = "".join(
        c for c in (title or "") if c.isalnum() or c in " -_()&'.,"
    ).strip()
    return cleaned[:120] or "audio"


@app.route("/api/mp3", methods=["POST"])
def mp3():
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()

    if not url or not valid_url(url):
        return jsonify({"error": "Enter a valid YouTube link."}), 400

    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        return jsonify(
            {"error": "FFmpeg is not available on this server, so MP3 cannot be created."}
        ), 503

    workdir = tempfile.mkdtemp(prefix="ytmp3-")
    try:
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "bestaudio/best",
            "outtmpl": os.path.join(workdir, "%(title).120B.%(ext)s"),
            "ffmpeg_location": ffmpeg,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

        files = glob.glob(os.path.join(workdir, "*.mp3"))
        if not files:
            raise RuntimeError("Conversion finished but no MP3 was produced.")

        audio_path = max(files, key=os.path.getsize)
        filename = safe_name(info.get("title")) + ".mp3"
        response = send_file(
            audio_path,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=filename,
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    except Exception as exc:
        return jsonify({"error": f"Could not create MP3: {exc}"}), 502
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
