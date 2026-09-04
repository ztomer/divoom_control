"""Scheduling, SPP mode, display-mode, and lookup-table constants.

Split out of constants.py to keep each file under 500 LOC (REVIEW §1). Re-exported
by constants.py via ``from .constants_scheduling import *`` so the public surface
(``divoom_lib.models.*``) is unchanged.
"""

# TIMEPLAN CONSTANTS (from timeplan.py)
# Set Time Manage Info Parameter Offsets and Lengths
STMI_STATUS = 0
STMI_HOUR = 1
STMI_MINUTE = 2
STMI_WEEK = 3
STMI_MODE = 4
STMI_TRIGGER_MODE = 5
STMI_FM_FREQ_START = 6
STMI_FM_FREQ_LENGTH = 2
STMI_VOLUME = 8
STMI_TYPE = 9
STMI_ANIMATION_ID = 10
STMI_ANIMATION_SPEED = 11
STMI_ANIMATION_DIRECTION = 12
STMI_ANIMATION_FRAME_COUNT = 13
STMI_ANIMATION_FRAME_DELAY = 14
STMI_ANIMATION_FRAME_DATA_START = 15

# Set Time Manage Info Type Values
STMI_TYPE_0 = 0
STMI_TYPE_1 = 1

# Set Time Manage Control Parameter Values
STMC_STATUS = 0
STMC_INDEX = 1

# SYSTEM WORK MODES (from system_settings.md)
SPP_DEFINE_MODE_BT = 0
SPP_DEFINE_MODE_FM = 1
SPP_DEFINE_MODE_LINEIN = 2
SPP_DEFINE_MODE_SD = 3
SPP_DEFINE_MODE_USBHOST = 4
SPP_DEFINE_MODE_RECORD = 5
SPP_DEFINE_MODE_RECORDPLAY = 6
SPP_DEFINE_MODE_UAC = 7
SPP_DEFINE_MODE_PHONE = 8
SPP_DEFINE_MODE_DIVOOM_SHOW = 9
SPP_DEFINE_MODE_ALARM_SET = 10
SPP_DEFINE_MODE_GAME = 11

# LIGHT MODES (from light.md)
DIVOOM_DISP_ENV_MODE = 0
DIVOOM_DISP_LIGHT_MODE = 1
DIVOOM_DISP_DIVOOM_MODE = 2
DIVOOM_DISP_SPECIAL_MODE = 3
DIVOOM_DISP_MUISE_MODE = 4
DIVOOM_DISP_USER_DEFINE_MODE = 5
DIVOOM_DISP_SCORE_MODE = 6

# TOOL TYPES (from tool.md)
DIVOOM_DISP_WATCH_MODE = 0
DIVOOM_DISP_SCORE_MODE = 1
DIVOOM_DISP_NOISE_MODE = 2
DIVOOM_DISP_COUNT_TIME_DOWN = 3

# TIME DISPLAY TYPES (from node-divoom-timebox-evo/src/types.ts)
class TimeDisplayType:
    FullScreen = 0
    Rainbow = 1
    WithBox = 2
    AnalogSquare = 3
    FullScreenNegative = 4
    AnalogRound = 5

# LIGHTNING TYPES (from node-divoom-timebox-evo/src/types.ts)
class LightningType:
    PlainColor = 0
    Love = 1
    Plants = 2
    NoMosquitto = 3
    Sleeping = 4

# WEATHER TYPES (from node-divoom-timebox-evo/src/types.ts)
class WeatherType:
    Clear = 1
    CloudySky = 3
    Thunderstorm = 5
    Rain = 6
    Snow = 8
    Fog = 9

# VJ EFFECT TYPES (from node-divoom-timebox-evo/src/types.ts)
class VJEffectType:
    Sparkles = 0
    Lava = 1
    VerticalRainbowLines = 2
    Drops = 3
    RainbowSwirl = 4
    CMYFade = 5
    RainbowLava = 6
    PastelPatterns = 7
    CMYWave = 8
    Fire = 9
    Countdown = 10
    PinkBlueFade = 11
    RainbowPolygons = 12
    PinkBlueWave = 13
    RainbowCross = 14
    RainbowShapes = 15

# Notification mirroring app types (SPP_SET_ANDROID_ANCS, cmd 0x50).
# Source: APK SppProc NOTIFICATION_APPS enum. NOTE: the device wire protocol
# skips slot 8 — for app_type >= 8 the byte sent is app_type + 1 (replicated in
# divoom_lib.tools.notification, matching CmdManager.a0).
NOTIFICATION_APPS = {
    "KAKAO": 1,
    "INSTAGRAM": 2,
    "SNAPCHAT": 3,
    "FACEBOOK": 4,
    "TWITTER": 5,
    "WHATSAPP": 6,
    "TEXT_MESSAGE": 7,
    "SKYPE": 8,
    "LINE": 9,
    "WECHAT": 10,
    "QQ": 11,
    "VIBER": 12,
    "MESSENGER": 13,
    "OK": 14,
}

# TIMEBOX_CONST in Node.js library
TIMEBOX_CONST = {
    "TimeType": TimeDisplayType,
    "LightningType": LightningType,
    "WeatherType": WeatherType,
    "VJEffectType": VJEffectType
}
