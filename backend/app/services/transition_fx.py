"""Locally generated power-hour transitions: corner countdown, canned animation, sound cues.

Two styles, both built entirely with ffmpeg filters (no bundled assets):

* **Animated card** (``build_animated_card``): a dark card with sweeping accent bars and CRT
  scanlines. A headline slides in and an optional subline fades in while a small 3·2·1
  countdown ticks in the top-right corner (a tick beep each second over a rising riser
  tone). At the hit, a white flash, a screen shake and a punch-zoomed call word
  ("DRINK!", "SHOT!", ...) land on a recorded drink cue (beer can, clink, pop, ...).
* **Video transition** (``build_video_transition``): a short clip plays, the same corner
  countdown ticks over its last three seconds, then the last frame freezes and darkens
  while the call word punches in on a flash with the drink cue.

Every piece of text is written to a file and drawn with ``textfile=...:expansion=none``.
ffmpeg runs with its working directory set to the temp folder holding those files, so the
filter graph only ever contains bare names like ``headline.txt`` (no drive-letter colons on
Windows, nothing a caller can inject). Colors must be ``#RRGGBB`` (callers validate).
"""

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# Timeline constants (seconds).
COUNTDOWN_SECONDS = 3  # the corner countdown always runs 3·2·1, one number per second
CARD_HIT_SECONDS = 2.5  # how long a card holds after the hit
CARD_SECONDS = COUNTDOWN_SECONDS + CARD_HIT_SECONDS  # default animated card length (5.5s)
MIN_HIT_SECONDS = 1.5
VIDEO_CLIP_SECONDS = 4.0  # default length of the found clip inside a video transition
MOMENT_PAD_SECONDS = 6.0  # source kept either side of the picked moment, so it can be re-trimmed
MIN_TRIM_SECONDS = 1.0  # shortest clip a user trim may leave before the stinger
MIN_VIDEO_CLIP_SECONDS = 1.0  # the user picks the range now, so allow short and
MAX_VIDEO_CLIP_SECONDS = 20.0  # ...longer moments than the AI default
VIDEO_TAIL_SECONDS = 1.8  # freeze-frame + DRINK beat appended after the clip

# Drink cues: all recorded (app/assets/transitions/sounds). The user picked these; the old
# synthesized horn / buzzer / bell are gone. Order = how pickers list them.
SOUNDS = ("can", "clink", "pop", "pour", "cheer", "bell")
DEFAULT_SOUND = "can"
HIT_WORDS = ("DRINK!", "SHOT!", "CHEERS!", "BOTTOMS UP!", "CHUG!")
FPS = 30
SAMPLE_RATE = 44100
STINGER_SECONDS = 2.2  # the "DRINK!" art beat that ends a clip transition
STINGER_HIT_AT = 0.12
CUE_MAX_SECONDS = 2.0  # a recorded cue is cut (with a fade) to this length

# Bundled assets: drink art (fallback when no AI art) and an optional recorded sound pack.
ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "transitions"
ART_DIR = ASSET_DIR / "art"
SOUND_DIR = ASSET_DIR / "sounds"
_AUDIO_EXTS = (".ogg", ".mp3", ".wav", ".m4a", ".flac")
# Cue name -> file stem in SOUND_DIR. A cue is only offered when its file is present.
RECORDED_SOUNDS = {
    "can": "beer_can",
    "clink": "glass_clink",
    "pop": "bottle_pop",
    "pour": "beer_pour",
    "cheer": "crowd_cheer",
    "bell": "boxing_bell",
}


def sound_file(name: str) -> Path | None:
    """The recorded file for a cue name, if the sound pack has one."""
    stem = RECORDED_SOUNDS.get(name)
    if not stem:
        return None
    for ext in _AUDIO_EXTS:
        path = SOUND_DIR / f"{stem}{ext}"
        if path.is_file():
            return path
    return None


def available_sounds() -> tuple[str, ...]:
    """Every cue name usable right now (its recording is present)."""
    return tuple(name for name in SOUNDS if sound_file(name))


def usable_sound(name: str) -> str:
    """``name`` if its recording exists, else the default cue (or the first available one)."""
    available = available_sounds()
    if name in available:
        return name
    if DEFAULT_SOUND in available or not available:
        return DEFAULT_SOUND
    return available[0]


def bundled_art() -> list[Path]:
    """The fallback drink art shipped with the app (shot glass, beer mugs, ...)."""
    if not ART_DIR.is_dir():
        return []
    return sorted(p for p in ART_DIR.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))


def pick_bundled_art(index: int) -> Path | None:
    art = bundled_art()
    return art[index % len(art)] if art else None


# ─── sound: aevalsrc expressions (all numbers ours, never caller text) ─────────────

def _f(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def _env(a: float, b: float, attack: float = 60.0, release: float = 25.0) -> str:
    """Gate between a and b with a short linear attack and release (avoids clicks)."""
    return f"between(t,{_f(a)},{_f(b)})*min(1,(t-{_f(a)})*{_f(attack)})*min(1,({_f(b)}-t)*{_f(release)})"


def _thump(at: float) -> str:
    """A low impact hit with a falling pitch, under every cue."""
    tau = f"(t-{_f(at)})"
    return f"0.75*sin(2*PI*(110*{tau}-60*{tau}*{tau}))*exp(-{tau}*7)*between(t,{_f(at)},{_f(at + 0.8)})"


def _ticks(start: float, count: int = COUNTDOWN_SECONDS) -> str:
    """One short beep per countdown second; the last one is higher."""
    beeps = []
    for i in range(count):
        a = start + i
        freq = 1568 if i == count - 1 else 1047
        beeps.append(f"0.3*sin(2*PI*{freq}*t)*{_env(a, a + 0.09, 400, 80)}")
    return "+".join(beeps)


def _riser(start: float, length: float) -> str:
    """Quiet rising tone (200 -> 800 Hz) under the countdown to build tension."""
    tau = f"(t-{_f(start)})"
    sweep = 600 / (2 * length)
    return f"0.07*sin(2*PI*(200*{tau}+{_f(sweep)}*{tau}*{tau}))*{_env(start, start + length, 8, 30)}"


def cue_expression(sound: str, hit_at: float, countdown_at: float | None, riser: bool) -> str:
    """The generated part of a transition soundtrack as one aevalsrc expression: the thump on
    the hit plus the countdown ticks. The drink cue itself is always a recording (mixed in by
    ``_cue_audio``); with no recording available the hit is just the thump."""
    parts = [_thump(hit_at)]
    if countdown_at is not None:
        parts.append(_ticks(countdown_at))
        if riser:
            parts.append(_riser(countdown_at, hit_at - countdown_at))
    return "+".join(parts)


def _aevalsrc(expr: str, duration: float, label: str) -> str:
    return (
        f"aevalsrc=exprs='{expr}':s={SAMPLE_RATE}:d={_f(duration)},"
        f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo,"
        f"alimiter=limit=0.95[{label}]"
    )


# ─── video: drawtext helpers (text always from files) ─────────────────────────────

def _font_size(text: str, width: int, height: int, max_ratio: float) -> int:
    """Largest size (<= max_ratio of the height) that keeps ``text`` inside ~90% of the width."""
    fit = int((width * 0.9) / (0.62 * max(len(text), 1)))
    return max(18, min(int(height * max_ratio), fit))


def _hex(color: str) -> str:
    return "0x" + color.lstrip("#")


# Bold fonts tried in order (Docker image, typical Linux, macOS, Windows). The first that
# exists is copied next to the text files as ``font.ttf`` so the filter never contains a path.
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)
FONT_NAME = "font.ttf"


def _find_font() -> Path | None:
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def _font_opt() -> str:
    """``:fontfile=font.ttf`` when a bundled-with-the-OS bold font exists, else "" (fontconfig)."""
    return f":fontfile={FONT_NAME}" if _find_font() else ""


def _drawtext(fname: str, size: int, color: str, x: str, y: str, enable: str, extra: str = "") -> str:
    return (
        f"drawtext=textfile={fname}:expansion=none{_font_opt()}:fontsize={size}:fontcolor={color}:"
        f"x='{x}':y='{y}':enable='{enable}'{extra}"
    )


def _corner_countdown(start: float, width: int, height: int, color: str) -> list[str]:
    """Small 3·2·1 in the top-right corner, one number per second, each with a tiny pop."""
    size = max(28, int(height * 0.11))
    pop = int(size * 1.3)
    pad = max(6, int(height * 0.018))
    x = f"w-text_w-w*0.035-{pad}"
    y = f"h*0.05+{pad}"
    box = f":box=1:boxcolor=black@0.65:boxborderw={pad}:borderw=2:bordercolor=black"
    label_size = max(14, int(height * 0.028))
    filters = [
        _drawtext(
            "corner_label.txt", label_size, "white@0.85", f"w-text_w-w*0.035-{pad}", "h*0.05-text_h+2",
            f"between(t,{_f(start)},{_f(start + COUNTDOWN_SECONDS)})",
        )
    ]
    for i in range(COUNTDOWN_SECONDS):
        a = start + i
        fname = f"corner_{COUNTDOWN_SECONDS - i}.txt"
        filters.append(_drawtext(fname, pop, color, x, y, f"between(t,{_f(a)},{_f(a + 0.1)})", box))
        filters.append(_drawtext(fname, size, color, x, y, f"between(t,{_f(a + 0.1)},{_f(a + 1)})", box))
    return filters


def _hit_word(hit_at: float, end: float, width: int, height: int, fg: str, y_center: str) -> list[str]:
    """Punch-zoom the call word in (big -> settle), then strobe it between fg and white."""
    base = _font_size("BOTTOMS UP!", width, height, 0.26)  # same size for every call word
    x = "(w-text_w)/2"
    y = f"{y_center}-text_h/2"
    border = f":borderw={max(4, int(height * 0.011))}:bordercolor=black"
    settle = hit_at + 0.14
    steady = f"between(t,{_f(settle)},{_f(end)})"
    return [
        _drawtext("hit.txt", int(base * 1.5), fg, x, y, f"between(t,{_f(hit_at)},{_f(hit_at + 0.07)})", border),
        _drawtext("hit.txt", int(base * 1.2), fg, x, y, f"between(t,{_f(hit_at + 0.07)},{_f(settle)})", border),
        _drawtext("hit.txt", base, fg, x, y, f"{steady}*lt(mod(t-{_f(settle)},0.5),0.3)", border),
        _drawtext("hit.txt", base, "white", x, y, f"{steady}*gte(mod(t-{_f(settle)},0.5),0.3)", border),
    ]


def _flash(hit_at: float, fg: str) -> list[str]:
    return [
        f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.85:t=fill:enable='between(t,{_f(hit_at)},{_f(hit_at + 0.1)})'",
        f"drawbox=x=0:y=0:w=iw:h=ih:color={fg}@0.4:t=fill:enable='between(t,{_f(hit_at + 0.1)},{_f(hit_at + 0.2)})'",
    ]


def _shake_crop(width: int, height: int, margin: int, hit_at: float, tick_until: float | None) -> str:
    """Crop the oversized canvas back to size, jittering the window: a hard shake after the
    hit and (optionally) a small bump on each countdown second."""
    hit = f"{margin}*0.9*max(0,1-(t-{_f(hit_at)})/0.7)*gte(t,{_f(hit_at)})"
    bump = f"+{margin}*0.3*lt(mod(t,1),0.12)*lt(t,{_f(tick_until)})" if tick_until else ""
    x = f"{margin}+({hit}{bump})*sin(t*83)"
    y = f"{margin}+({hit}{bump})*cos(t*71)"
    return f"crop={width}:{height}:x='{x}':y='{y}'"


def _scanlines() -> str:
    return "drawgrid=w=iw:h=4:t=1:c=black@0.22"


def _write_texts(tmp_dir: Path, texts: dict[str, str]) -> None:
    """Write every text (and the font, when one was found) into ffmpeg's working dir."""
    for name, content in texts.items():
        (tmp_dir / name).write_text(content, encoding="utf-8")
    font = _find_font()
    if font:
        shutil.copyfile(font, tmp_dir / FONT_NAME)


def _countdown_texts() -> dict[str, str]:
    texts = {f"corner_{n}.txt": str(n) for n in range(1, COUNTDOWN_SECONDS + 1)}
    texts["corner_label.txt"] = "NEXT SHOT"
    return texts


async def _run_ffmpeg(cmd: list[str], cwd: str, label: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        tail = stderr.decode(errors="replace")
        logger.error("FFmpeg %s failed: %s", label, tail[-800:])
        raise RuntimeError(f"Failed to build {label}: {tail[-200:]}")


_ENCODE = [
    "-c:v", "libx264", "-preset", "fast", "-crf", "21", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE), "-ac", "2",
    "-r", str(FPS), "-movflags", "+faststart",
]


def _size(resolution: str) -> tuple[int, int]:
    w, h = map(int, resolution.lower().split("x"))
    return w - w % 2, h - h % 2


# ─── style a: animated card ───────────────────────────────────────────────────────

def card_length(duration: float) -> float:
    """The real length of a card asked to last ``duration`` (it always fits countdown + hit)."""
    return round(max(duration, COUNTDOWN_SECONDS + MIN_HIT_SECONDS), 2)


def card_filter(
    width: int, height: int, duration: float, fg: str, bg: str, has_subline: bool, sound: str,
    recorded: bool = False,
) -> str:
    """filter_complex for an animated card (text comes from files in ffmpeg's cwd)."""
    hit_at = float(COUNTDOWN_SECONDS)
    margin = max(8, int(height * 0.03))
    cw, ch = width + 2 * margin, height + 2 * margin
    bar_a, bar_b = max(40, cw // 7), max(20, cw // 14)
    band = max(4, int(height * 0.014))
    d = _f(duration)

    head_size = _font_size("X" * 14, width, height, 0.15)
    sub_size = max(18, int(height * 0.055))
    build = f"lt(t,{_f(hit_at)})"
    text = [
        # headline slides in from the left with an ease-out, then bobs gently
        _drawtext(
            "headline.txt", head_size, fg,
            "(w-text_w)/2-w*pow(max(0,1-t/0.45),3)", "h*0.40-text_h/2+h*0.008*sin(t*4)", build,
            f":borderw={max(3, int(height * 0.008))}:bordercolor=black",
        ),
    ]
    if has_subline:
        text.append(_drawtext(
            "subline.txt", sub_size, "white", "(w-text_w)/2", "h*0.58",
            "1", ":alpha='min(1,max(0,(t-0.5)*3))':borderw=3:bordercolor=black",
        ))
    text += _hit_word(hit_at, duration, width, height, fg, "h*0.42")

    graph = [
        f"color=c={bg}:s={cw}x{ch}:r={FPS}:d={d},format=rgba[bg]",
        f"color=c={fg}@0.22:s={bar_a}x{ch}:r={FPS}:d={d},format=rgba[bara]",
        f"color=c={fg}@0.14:s={bar_b}x{ch}:r={FPS}:d={d},format=rgba[barb]",
        f"[bg][bara]overlay=x='mod(t*{int(cw * 0.6)},{cw + bar_a})-{bar_a}':y=0:shortest=1[b1]",
        f"[b1][barb]overlay=x='{cw}-mod(t*{int(cw * 1.1)},{cw + bar_b})':y=0:shortest=1,"
        + ",".join([
            f"drawbox=x=0:y={margin}:w=iw:h={band}:color={fg}:t=fill",
            f"drawbox=x=0:y=ih-{margin + band}:w=iw:h={band}:color={fg}:t=fill",
            *text,
            *_flash(hit_at, fg),
            _shake_crop(width, height, margin, hit_at, hit_at),
            _scanlines(),
            *_corner_countdown(0.0, width, height, fg),
            "format=yuv420p",
        ])
        + "[v]",
        _cue_audio("a", sound, hit_at, duration, 0.0, True, 0 if recorded else None),
    ]
    return ";".join(graph)


async def build_animated_card(
    output_path: str,
    headline: str,
    subline: str = "",
    text_color: str = "#FFE600",
    bg_color: str = "#000000",
    duration: float = CARD_SECONDS,
    resolution: str = "1280x720",
    hit_text: str = "DRINK!",
    sound: str = DEFAULT_SOUND,
) -> float:
    """Render an animated card. Returns its exact length in seconds."""
    width, height = _size(resolution)
    duration = card_length(duration)
    sound = usable_sound(sound)
    recorded = sound_file(sound)
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fg, bg = _hex(text_color), _hex(bg_color)

    with tempfile.TemporaryDirectory(prefix="ph_card_") as tmp:
        texts = {"headline.txt": headline, "hit.txt": hit_text or "DRINK!", **_countdown_texts()}
        if subline:
            texts["subline.txt"] = subline
        _write_texts(Path(tmp), texts)
        cmd = [settings.ffmpeg_path, "-y", "-hide_banner"]
        if recorded:
            cmd += ["-i", str(recorded.resolve())]
        cmd += [
            "-filter_complex", card_filter(width, height, duration, fg, bg, bool(subline), sound, bool(recorded)),
            "-map", "[v]", "-map", "[a]", "-t", _f(duration),
            *_ENCODE, str(output),
        ]
        await _run_ffmpeg(cmd, tmp, "animated card")
    return duration


# ─── style b: video clip + drink cue ──────────────────────────────────────────────

def video_filter(
    width: int, height: int, clip_seconds: float, fg: str, has_audio: bool, sound: str,
    show_text: bool = True, recorded: bool = False, countdown: bool = True,
) -> str:
    """filter_complex for a found clip followed by the freeze-frame beat: the call word over
    the darkened last frame, or (``show_text`` off) just the held frame and the cue.
    ``countdown`` off drops the corner 3-2-1 (the hand-built "hold last frame" ending)."""
    hit_at = clip_seconds
    total = clip_seconds + VIDEO_TAIL_SECONDS
    margin = max(8, int(height * 0.03))
    cw, ch = width + 2 * margin, height + 2 * margin
    countdown_at = max(0.0, clip_seconds - COUNTDOWN_SECONDS) if countdown else None
    after_hit = f"gte(t,{_f(hit_at)})"

    video = ",".join([
        f"[0:v]scale={cw}:{ch}:force_original_aspect_ratio=decrease",
        f"pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:black",
        "setsar=1",
        f"fps={FPS}",
        f"tpad=stop_mode=clone:stop_duration={_f(VIDEO_TAIL_SECONDS + 0.5)}",
        *([
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.55:t=fill:enable='{after_hit}'",
            *_hit_word(hit_at, total, width, height, fg, "h/2"),
            *_flash(hit_at, fg),
        ] if show_text else []),
        # No text: no shake either (a hit "after the end" never fires).
        _shake_crop(width, height, margin, hit_at if show_text else total + 10, None),
        *(_corner_countdown(countdown_at, width, height, fg) if countdown_at is not None else []),
        "format=yuv420p[v]",
    ])
    if has_audio:
        source = (
            f"[0:a]aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo,"
            f"afade=t=out:st={_f(max(0.0, hit_at - 0.35))}:d=0.35,apad[src]"
        )
    else:
        source = f"anullsrc=r={SAMPLE_RATE}:cl=stereo[src]"
    cue = _cue_audio("cue", sound, hit_at, total, countdown_at, False, 1 if recorded else None)
    mix = "[src][cue]amix=inputs=2:duration=shortest:dropout_transition=0,volume=2,alimiter=limit=0.95[a]"
    return ";".join([video, source, cue, mix])


async def _has_audio_stream(path: str) -> bool:
    ffmpeg = Path(settings.ffmpeg_path)
    ffprobe = str(ffmpeg.with_name("ffprobe" + ffmpeg.suffix)) if ffmpeg.parent != Path(".") else "ffprobe"
    try:
        proc = await asyncio.create_subprocess_exec(
            ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
            "-of", "csv=p=0", path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return proc.returncode == 0 and bool(stdout.strip())
    except Exception:  # pragma: no cover - missing ffprobe: assume audio, ffmpeg will say if not
        return True


async def build_video_transition(
    output_path: str,
    video_path: str,
    start: float = 0.0,
    clip_seconds: float = VIDEO_CLIP_SECONDS,
    resolution: str = "1280x720",
    text_color: str = "#FFE600",
    hit_text: str = "DRINK!",
    sound: str = DEFAULT_SOUND,
) -> float:
    """Render ``clip_seconds`` of ``video_path`` from ``start`` with the corner countdown over
    its last seconds, then the freeze-frame call word and drink cue. Returns the length."""
    width, height = _size(resolution)
    clip_seconds = round(min(max(clip_seconds, MIN_VIDEO_CLIP_SECONDS), MAX_VIDEO_CLIP_SECONDS), 2)
    total = round(clip_seconds + VIDEO_TAIL_SECONDS, 2)
    sound = usable_sound(sound)
    recorded = sound_file(sound)
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source = str(Path(video_path).resolve())
    has_audio = await _has_audio_stream(source)

    show_text = bool((hit_text or "").strip())
    with tempfile.TemporaryDirectory(prefix="ph_vtrans_") as tmp:
        _write_texts(Path(tmp), {"hit.txt": hit_text.strip() if show_text else " ", **_countdown_texts()})
        cmd = [
            settings.ffmpeg_path, "-y", "-hide_banner",
            "-ss", _f(max(0.0, start)), "-t", _f(clip_seconds), "-i", source,
            *(["-i", str(recorded.resolve())] if recorded else []),
            "-filter_complex",
            video_filter(width, height, clip_seconds, _hex(text_color), has_audio, sound, show_text, bool(recorded)),
            "-map", "[v]", "-map", "[a]", "-t", _f(total),
            *_ENCODE, str(output),
        ]
        await _run_ffmpeg(cmd, tmp, "video transition")
    return total


# ─── style c: drink art (shot glass / beer / AI art) ──────────────────────────────
#
# A still image (bundled drink art or per-project AI art) drifts slowly while the corner
# countdown ticks; at the hit it darkens, flashes and shakes while the call word punches in
# on the cue. The same art also makes the short "stinger" that ends a clip transition.

def _art_video(
    index: int, width: int, height: int, duration: float, hit_at: float, fg: str,
    countdown_at: float | None,
) -> str:
    """Video chain from ``[index:v]`` (a looped still image); text comes from files."""
    margin = max(8, int(height * 0.03))
    cover_w = int((width + 2 * margin) * 1.12)
    cover_h = int((height + 2 * margin) * 1.12)
    # Slow horizontal drift across the oversized image, plus the shake after the hit.
    hit = f"{margin}*0.9*max(0,1-(t-{_f(hit_at)})/0.7)*gte(t,{_f(hit_at)})"
    x = f"(iw-{width})/2+(iw-{width})*0.35*sin(t*0.45-0.6)+({hit})*sin(t*83)"
    y = f"(ih-{height})/2+({hit})*cos(t*71)"
    after = f"gte(t,{_f(hit_at)})"
    band_top, band_h = int(height * 0.29), int(height * 0.42)
    parts = [
        f"[{index}:v]scale=w='max({cover_w},{cover_h}*iw/ih)':h=-2",
        f"fps={FPS}",
        f"crop={width}:{height}:x='{x}':y='{y}'",
        "setsar=1",
        # Blend overlays in RGB: in YUV a translucent black box also drains the color.
        "format=rgba",
        f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.12:t=fill:enable='{after}'",
        f"drawbox=x=0:y={band_top}:w=iw:h={band_h}:color=black@0.38:t=fill:enable='{after}'",
        *_flash(hit_at, fg),
        *_hit_word(hit_at, duration, width, height, fg, "h/2"),
    ]
    if countdown_at is not None:
        parts += _corner_countdown(countdown_at, width, height, fg)
    parts.append("format=yuv420p")
    return ",".join(parts)


def _cue_audio(
    label: str, sound: str, hit_at: float, total: float, countdown_at: float | None,
    riser: bool, recorded_index: int | None,
) -> str:
    """Audio chain producing ``[label]``: countdown ticks + the drink cue at ``hit_at``.

    With a recorded cue (input ``recorded_index``) the file plays at the hit over generated
    ticks and a thump; otherwise the whole track is generated."""
    if recorded_index is None:
        return _aevalsrc(cue_expression(sound, hit_at, countdown_at, riser), total, label)
    parts = [_thump(hit_at)]
    if countdown_at is not None:
        parts.append(_ticks(countdown_at))
        if riser:
            parts.append(_riser(countdown_at, hit_at - countdown_at))
    delay = int(round(hit_at * 1000))
    fade_at = max(0.0, CUE_MAX_SECONDS - 0.35)
    return ";".join([
        _aevalsrc("+".join(parts), total, f"{label}_gen"),
        (
            f"[{recorded_index}:a]atrim=0:{_f(CUE_MAX_SECONDS)},asetpts=PTS-STARTPTS,"
            f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo,"
            f"afade=t=out:st={_f(fade_at)}:d=0.35,adelay={delay}|{delay},"
            f"apad=whole_dur={_f(total)}[{label}_rec]"
        ),
        (
            f"[{label}_gen][{label}_rec]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            f"alimiter=limit=0.95[{label}]"
        ),
    ])


def art_card_filter(width: int, height: int, duration: float, fg: str, sound: str, recorded: bool) -> str:
    """filter_complex for an art card: input 0 = the looped image, input 1 = recorded cue."""
    hit_at = float(COUNTDOWN_SECONDS)
    video = _art_video(0, width, height, duration, hit_at, fg, 0.0) + "[v]"
    audio = _cue_audio("a", sound, hit_at, duration, 0.0, True, 1 if recorded else None)
    return ";".join([video, audio])


async def build_art_card(
    output_path: str,
    art_path: str,
    text_color: str = "#FFE600",
    duration: float = CARD_SECONDS,
    resolution: str = "1280x720",
    hit_text: str = "DRINK!",
    sound: str = DEFAULT_SOUND,
) -> float:
    """Drink art + corner 3·2·1 + call word on the cue. Returns the exact length."""
    width, height = _size(resolution)
    duration = card_length(duration)
    sound = usable_sound(sound)
    recorded = sound_file(sound)
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ph_art_") as tmp:
        _write_texts(Path(tmp), {"hit.txt": hit_text or "DRINK!", **_countdown_texts()})
        cmd = [
            settings.ffmpeg_path, "-y", "-hide_banner",
            "-loop", "1", "-framerate", str(FPS), "-t", _f(duration),
            "-i", str(Path(art_path).resolve()),
        ]
        if recorded:
            cmd += ["-i", str(recorded.resolve())]
        cmd += [
            "-filter_complex",
            art_card_filter(width, height, duration, _hex(text_color), sound, bool(recorded)),
            "-map", "[v]", "-map", "[a]", "-t", _f(duration),
            *_ENCODE, str(output),
        ]
        await _run_ffmpeg(cmd, tmp, "art card")
    return duration


def clip_stinger_filter(
    width: int, height: int, clip_seconds: float, fg: str, has_audio: bool, sound: str,
    countdown: bool, stinger: bool, recorded: bool,
) -> str:
    """filter_complex: input 0 = the clip (cut to ``clip_seconds`` by the caller), input 1 =
    the looped stinger art (when ``stinger``), input 2 = recorded cue (when ``recorded``).

    The clip gets the corner countdown over its last three seconds (ticks over its own
    audio); then the art stinger lands the call word on the drink cue."""
    countdown_at = max(0.0, clip_seconds - COUNTDOWN_SECONDS) if countdown else None
    clip_video = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
        "setsar=1",
        f"fps={FPS}",
        f"trim=duration={_f(clip_seconds)}",
        "setpts=PTS-STARTPTS",
    ]
    if countdown_at is not None:
        clip_video += _corner_countdown(countdown_at, width, height, fg)
    clip_video.append("format=yuv420p")
    graph = [",".join(clip_video) + "[va]"]

    if has_audio:
        graph.append(
            f"[0:a]aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo,"
            f"atrim=duration={_f(clip_seconds)},asetpts=PTS-STARTPTS,"
            f"afade=t=out:st={_f(max(0.0, clip_seconds - 0.35))}:d=0.35,"
            f"apad=whole_dur={_f(clip_seconds)}[src]"
        )
    else:
        graph.append(f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=duration={_f(clip_seconds)}[src]")
    if countdown_at is not None:
        graph.append(_aevalsrc(_ticks(countdown_at), clip_seconds, "ticks"))
        graph.append(
            "[src][ticks]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            "alimiter=limit=0.95[aa]"
        )
    else:
        graph.append("[src]anull[aa]")

    if not stinger:
        graph.append("[va]null[v]")
        graph.append("[aa]anull[a]")
        return ";".join(graph)

    graph.append(_art_video(1, width, height, STINGER_SECONDS, STINGER_HIT_AT, fg, None) + "[vb]")
    graph.append(
        _cue_audio("ab", sound, STINGER_HIT_AT, STINGER_SECONDS, None, False, 2 if recorded else None)
    )
    graph.append("[va][aa][vb][ab]concat=n=2:v=1:a=1[v][a]")
    return ";".join(graph)


async def probe_duration(path: str) -> float:
    ffmpeg = Path(settings.ffmpeg_path)
    ffprobe = str(ffmpeg.with_name("ffprobe" + ffmpeg.suffix)) if ffmpeg.parent != Path(".") else "ffprobe"
    proc = await asyncio.create_subprocess_exec(
        ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0


async def build_clip_with_stinger(
    output_path: str,
    video_path: str,
    start: float = 0.0,
    clip_seconds: float | None = None,
    resolution: str = "1280x720",
    text_color: str = "#FFE600",
    countdown: bool = True,
    art_path: str | None = None,
    hit_text: str = "DRINK!",
    sound: str = DEFAULT_SOUND,
    hold_frame: bool = False,
) -> float:
    """A clip with the corner countdown over its end, then (when ``art_path``) the drink-art
    stinger with the call word and cue, or (``hold_frame``) no art at all: the call word and
    cue over the clip's own held last frame, like an AI video transition.
    ``clip_seconds=None`` uses the rest of the file. Returns the length of the result."""
    width, height = _size(resolution)
    source = str(Path(video_path).resolve())
    if clip_seconds is None:
        clip_seconds = max(0.5, (await probe_duration(source)) - max(0.0, start))
    clip_seconds = round(clip_seconds, 2)
    if hold_frame:
        return await _clip_with_held_frame(
            output_path, source, start, clip_seconds, width, height, text_color, countdown, hit_text, sound
        )
    sound = usable_sound(sound)
    recorded = sound_file(sound) if art_path else None
    has_audio = await _has_audio_stream(source)
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    total = clip_seconds + (STINGER_SECONDS if art_path else 0.0)

    with tempfile.TemporaryDirectory(prefix="ph_stinger_") as tmp:
        _write_texts(Path(tmp), {"hit.txt": hit_text or "DRINK!", **_countdown_texts()})
        cmd = [
            settings.ffmpeg_path, "-y", "-hide_banner",
            "-ss", _f(max(0.0, start)), "-t", _f(clip_seconds), "-i", source,
        ]
        if art_path:
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", _f(STINGER_SECONDS),
                    "-i", str(Path(art_path).resolve())]
        if recorded:
            cmd += ["-i", str(recorded.resolve())]
        cmd += [
            "-filter_complex",
            clip_stinger_filter(
                width, height, clip_seconds, _hex(text_color), has_audio, sound,
                countdown, bool(art_path), bool(recorded),
            ),
            "-map", "[v]", "-map", "[a]", "-t", _f(total),
            *_ENCODE, str(output),
        ]
        await _run_ffmpeg(cmd, tmp, "clip transition")
    return round(total, 2)


async def _clip_with_held_frame(
    output_path: str, source: str, start: float, clip_seconds: float, width: int, height: int,
    text_color: str, countdown: bool, hit_text: str, sound: str,
) -> float:
    """The video-only ending: the clip, then the call word + cue over its frozen last frame."""
    sound = usable_sound(sound)
    recorded = sound_file(sound)
    has_audio = await _has_audio_stream(source)
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    total = round(clip_seconds + VIDEO_TAIL_SECONDS, 2)
    show_text = bool((hit_text or "").strip())
    with tempfile.TemporaryDirectory(prefix="ph_holdframe_") as tmp:
        _write_texts(Path(tmp), {"hit.txt": hit_text.strip() if show_text else " ", **_countdown_texts()})
        cmd = [
            settings.ffmpeg_path, "-y", "-hide_banner",
            "-ss", _f(max(0.0, start)), "-t", _f(clip_seconds), "-i", source,
            *(["-i", str(recorded.resolve())] if recorded else []),
            "-filter_complex",
            video_filter(
                width, height, clip_seconds, _hex(text_color), has_audio, sound,
                show_text, bool(recorded), countdown,
            ),
            "-map", "[v]", "-map", "[a]", "-t", _f(total),
            *_ENCODE, str(output),
        ]
        await _run_ffmpeg(cmd, tmp, "clip transition (held frame)")
    return total


async def cut_window(source: str, output_path: str, start: float, seconds: float) -> float:
    """Cut ``seconds`` of ``source`` from ``start`` into a small standalone file (re-encoded,
    so the cut is frame-accurate). Keeps the original size; used as the re-trim source of a
    video transition. Returns the real length."""
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ph_window_") as tmp:
        cmd = [
            settings.ffmpeg_path, "-y", "-hide_banner",
            "-ss", _f(max(0.0, start)), "-t", _f(seconds), "-i", str(Path(source).resolve()),
            "-map", "0:v:0", "-map", "0:a:0?", *_ENCODE, str(output),
        ]
        await _run_ffmpeg(cmd, tmp, "transition source window")
    return round(await probe_duration(str(output)), 2)
