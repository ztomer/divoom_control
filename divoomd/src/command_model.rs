//! The command model as a TYPE, GENERATED from `divoom_lib.models.COMMANDS`.
//! Do not edit by hand; regenerate via `scripts/codegen/gen_commands.py`.
//! @generated

use crate::command_names::CANONICAL_NAMES;

/// Every command as a TYPE: one variant per protocol id.
///
/// The protocol is id-first — 109 names, 105 ids, four ids with two
/// names each — so the enum is too, and the second spelling is a
/// `#[doc(alias)]`. A `match` over it is exhaustive: a command the
/// protocol adds is a compile error at every dispatch site instead of a
/// runtime `None` nobody reads.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
#[repr(u8)]
pub enum Command {
    /// `set volume`
    SetVolume = 0x08,
    /// `set playstate`
    SetPlaystate = 0x0a,
    /// `set gif speed`
    SetGifSpeed = 0x16,
    /// `set game ctrl info`
    SetGameCtrlInfo = 0x17,
    /// `set date time`
    SetDateTime = 0x18,
    /// `app send eq gif`
    AppSendEqGif = 0x1b,
    /// `set game ctrl key up info`
    SetGameCtrlKeyUpInfo = 0x21,
    /// `set keyboard`
    SetKeyboard = 0x23,
    /// `set hot`
    SetHot = 0x26,
    /// `send hotctrl`
    SendHotctrl = 0x85,
    /// `send hot file list`
    SendHotFileList = 0x9b,
    /// `hot update file info`
    HotUpdateFileInfo = 0x9d,
    /// `hot send file data`
    HotSendFileData = 0x9e,
    /// `hot pause file send`
    HotPauseFileSend = 0x9f,
    /// `request new file info`
    RequestNewFileInfo = 0xf7,
    /// `set blue password`
    SetBluePassword = 0x27,
    /// `sand paint ctrl`
    SandPaintCtrl = 0x34,
    /// `pic scan ctrl`
    PicScanCtrl = 0x35,
    /// `drawing mul pad ctrl`
    DrawingMulPadCtrl = 0x3a,
    /// `drawing big pad ctrl`
    DrawingBigPadCtrl = 0x3b,
    /// `set temp type`
    SetTempType = 0x2b,
    /// `set time type`
    SetTimeType = 0x2c,
    /// `set lightness`
    SetLightness = 0x32,
    /// `set sleeptime`
    SetSleeptime = 0x40,
    /// `set sleep scene`
    SetSleepScene = 0x41,
    /// `get alarm time`
    GetAlarmTime = 0x42,
    /// `set alarm`
    SetAlarm = 0x43,
    #[doc(alias = "set image")]
    /// `set light pic` / `set image`
    SetLightPic = 0x44,
    #[doc(alias = "set light phone gif")]
    /// `set animation frame` / `set light phone gif`
    SetAnimationFrame = 0x49,
    #[doc(alias = "set channel light")]
    /// `set light mode` / `set channel light`
    SetLightMode = 0x45,
    /// `get light mode`
    GetLightMode = 0x46,
    /// `app need get music list`
    AppNeedGetMusicList = 0x47,
    /// `set alarm gif`
    SetAlarmGif = 0x51,
    /// `set temp unit`
    SetTempUnit = 0x4c,
    /// `set android ancs`
    SetAndroidAncs = 0x50,
    /// `set boot gif`
    SetBootGif = 0x52,
    /// `get memorial time`
    GetMemorialTime = 0x53,
    /// `set memorial`
    SetMemorial = 0x54,
    /// `set memorial gif`
    SetMemorialGif = 0x55,
    /// `set time manage info`
    SetTimeManageInfo = 0x56,
    /// `set time manage ctrl`
    SetTimeManageCtrl = 0x57,
    /// `drawing pad ctrl`
    DrawingPadCtrl = 0x58,
    /// `get device temp`
    GetDeviceTemp = 0x59,
    /// `drawing pad exit`
    DrawingPadExit = 0x5a,
    /// `drawing mul encode single pic`
    DrawingMulEncodeSinglePic = 0x5b,
    /// `drawing mul encode pic`
    DrawingMulEncodePic = 0x5c,
    /// `send net temp`
    SendNetTemp = 0x5d,
    /// `send net temp disp`
    SendNetTempDisp = 0x5e,
    #[doc(alias = "send current temp")]
    /// `set temp` / `send current temp`
    SetTemp = 0x5f,
    /// `set radio frequency`
    SetRadioFrequency = 0x61,
    /// `drawing mul encode gif play`
    DrawingMulEncodeGifPlay = 0x6b,
    /// `drawing encode movie play`
    DrawingEncodeMoviePlay = 0x6c,
    /// `drawing mul encode movie play`
    DrawingMulEncodeMoviePlay = 0x6d,
    /// `drawing ctrl movie play`
    DrawingCtrlMoviePlay = 0x6e,
    /// `drawing mul pad enter`
    DrawingMulPadEnter = 0x6f,
    /// `get tool info`
    GetToolInfo = 0x71,
    /// `set tool`
    SetTool = 0x72,
    /// `get net temp disp`
    GetNetTempDisp = 0x73,
    /// `set brightness`
    SetBrightness = 0x74,
    /// `set device name`
    SetDeviceName = 0x75,
    /// `get device name`
    GetDeviceName = 0x76,
    /// `get sd music list total num`
    GetSdMusicListTotalNum = 0x7d,
    /// `set alarm vol ctrl`
    SetAlarmVolCtrl = 0x82,
    /// `set song dis ctrl`
    SetSongDisCtrl = 0x83,
    /// `set light phone word attr`
    SetLightPhoneWordAttr = 0x87,
    /// `set text content`
    SetTextContent = 0x86,
    /// `send game shark`
    SendGameShark = 0x88,
    /// `set poweron channel`
    SetPoweronChannel = 0x8a,
    /// `app new send gif cmd`
    AppNewSendGifCmd = 0x8b,
    /// `app new user define`
    AppNewUserDefine = 0x8c,
    /// `app big64 user define`
    AppBig64UserDefine = 0x8d,
    /// `app get user define info`
    AppGetUserDefineInfo = 0x8e,
    /// `set game`
    SetGame = 0xa0,
    /// `get sleep scene`
    GetSleepScene = 0xa2,
    /// `set sleep scene listen`
    SetSleepSceneListen = 0xa3,
    /// `set scene vol`
    SetSceneVol = 0xa4,
    /// `set alarm listen`
    SetAlarmListen = 0xa5,
    /// `set alarm vol`
    SetAlarmVol = 0xa6,
    /// `set sound ctrl`
    SetSoundCtrl = 0xa7,
    /// `get sound ctrl`
    GetSoundCtrl = 0xa8,
    /// `set auto power off`
    SetAutoPowerOff = 0xab,
    /// `get auto power off`
    GetAutoPowerOff = 0xac,
    /// `set sleep color`
    SetSleepColor = 0xad,
    /// `set sleep light`
    SetSleepLight = 0xae,
    /// `set user gif`
    SetUserGif = 0xb1,
    /// `set low power switch`
    SetLowPowerSwitch = 0xb2,
    /// `get low power switch`
    GetLowPowerSwitch = 0xb3,
    /// `get sd music info`
    GetSdMusicInfo = 0xb4,
    /// `set sd music info`
    SetSdMusicInfo = 0xb5,
    /// `modify user gif items`
    ModifyUserGifItems = 0xb6,
    /// `set rhythm gif`
    SetRhythmGif = 0xb7,
    /// `set sd music position`
    SetSdMusicPosition = 0xb8,
    /// `set sd music play mode`
    SetSdMusicPlayMode = 0xb9,
    /// `set poweron voice vol`
    SetPoweronVoiceVol = 0xbb,
    /// `set design`
    SetDesign = 0xbd,
    /// `set work mode`
    SetWorkMode = 0x05,
    /// `get sd music list`
    GetSdMusicList = 0x07,
    /// `get volume`
    GetVolume = 0x09,
    /// `get play status`
    GetPlayStatus = 0x0b,
    /// `set sd play music id`
    SetSdPlayMusicId = 0x11,
    /// `set sd last next`
    SetSdLastNext = 0x12,
    /// `send sd list over`
    SendSdListOver = 0x14,
    /// `send sd status`
    SendSdStatus = 0x15,
    /// `get sd play name`
    GetSdPlayName = 0x06,
    /// `get work mode`
    GetWorkMode = 0x13,
}

impl Command {
    /// The protocol id this command is sent as.
    #[must_use]
    pub const fn id(self) -> u8 {
        self as u8
    }

    /// The canonical name, as the Python table spells it.
    ///
    /// A lookup in the table rather than a `match`: one arm per command
    /// is a function the size of the protocol, which is what the table
    /// already is. Aliases are not returned -- they resolve to the same
    /// command, and a command has one canonical spelling.
    #[must_use]
    pub fn name(self) -> &'static str {
        CANONICAL_NAMES
            .iter()
            .find(|(_, cmd)| *cmd == self)
            .map_or("", |(name, _)| *name)
    }
}

/// Every command, in protocol-table order. Iteration and exhaustive
/// tests start here rather than from a range of ids.
pub const ALL: &[Command] = &[
    Command::SetVolume,
    Command::SetPlaystate,
    Command::SetGifSpeed,
    Command::SetGameCtrlInfo,
    Command::SetDateTime,
    Command::AppSendEqGif,
    Command::SetGameCtrlKeyUpInfo,
    Command::SetKeyboard,
    Command::SetHot,
    Command::SendHotctrl,
    Command::SendHotFileList,
    Command::HotUpdateFileInfo,
    Command::HotSendFileData,
    Command::HotPauseFileSend,
    Command::RequestNewFileInfo,
    Command::SetBluePassword,
    Command::SandPaintCtrl,
    Command::PicScanCtrl,
    Command::DrawingMulPadCtrl,
    Command::DrawingBigPadCtrl,
    Command::SetTempType,
    Command::SetTimeType,
    Command::SetLightness,
    Command::SetSleeptime,
    Command::SetSleepScene,
    Command::GetAlarmTime,
    Command::SetAlarm,
    Command::SetLightPic,
    Command::SetAnimationFrame,
    Command::SetLightMode,
    Command::GetLightMode,
    Command::AppNeedGetMusicList,
    Command::SetAlarmGif,
    Command::SetTempUnit,
    Command::SetAndroidAncs,
    Command::SetBootGif,
    Command::GetMemorialTime,
    Command::SetMemorial,
    Command::SetMemorialGif,
    Command::SetTimeManageInfo,
    Command::SetTimeManageCtrl,
    Command::DrawingPadCtrl,
    Command::GetDeviceTemp,
    Command::DrawingPadExit,
    Command::DrawingMulEncodeSinglePic,
    Command::DrawingMulEncodePic,
    Command::SendNetTemp,
    Command::SendNetTempDisp,
    Command::SetTemp,
    Command::SetRadioFrequency,
    Command::DrawingMulEncodeGifPlay,
    Command::DrawingEncodeMoviePlay,
    Command::DrawingMulEncodeMoviePlay,
    Command::DrawingCtrlMoviePlay,
    Command::DrawingMulPadEnter,
    Command::GetToolInfo,
    Command::SetTool,
    Command::GetNetTempDisp,
    Command::SetBrightness,
    Command::SetDeviceName,
    Command::GetDeviceName,
    Command::GetSdMusicListTotalNum,
    Command::SetAlarmVolCtrl,
    Command::SetSongDisCtrl,
    Command::SetLightPhoneWordAttr,
    Command::SetTextContent,
    Command::SendGameShark,
    Command::SetPoweronChannel,
    Command::AppNewSendGifCmd,
    Command::AppNewUserDefine,
    Command::AppBig64UserDefine,
    Command::AppGetUserDefineInfo,
    Command::SetGame,
    Command::GetSleepScene,
    Command::SetSleepSceneListen,
    Command::SetSceneVol,
    Command::SetAlarmListen,
    Command::SetAlarmVol,
    Command::SetSoundCtrl,
    Command::GetSoundCtrl,
    Command::SetAutoPowerOff,
    Command::GetAutoPowerOff,
    Command::SetSleepColor,
    Command::SetSleepLight,
    Command::SetUserGif,
    Command::SetLowPowerSwitch,
    Command::GetLowPowerSwitch,
    Command::GetSdMusicInfo,
    Command::SetSdMusicInfo,
    Command::ModifyUserGifItems,
    Command::SetRhythmGif,
    Command::SetSdMusicPosition,
    Command::SetSdMusicPlayMode,
    Command::SetPoweronVoiceVol,
    Command::SetDesign,
    Command::SetWorkMode,
    Command::GetSdMusicList,
    Command::GetVolume,
    Command::GetPlayStatus,
    Command::SetSdPlayMusicId,
    Command::SetSdLastNext,
    Command::SendSdListOver,
    Command::SendSdStatus,
    Command::GetSdPlayName,
    Command::GetWorkMode,
];

impl TryFrom<u8> for Command {
    type Error = u8;

    /// Total in the sense that matters: every id this crate can name
    /// resolves, and an id outside the protocol is the error, not a
    /// silent default. (`as u8` on a `u16` off the wire would invent one,
    /// which is how a truncation becomes a command the device never
    /// receives.)
    ///
    /// A scan of `ALL`, not a `match` with an arm per id, for the reason
    /// `name()` gives. 105 comparisons of a `u8` is not a cost worth a
    /// jump table's correctness risk.
    fn try_from(value: u8) -> Result<Self, Self::Error> {
        ALL.iter()
            .find(|cmd| cmd.id() == value)
            .copied()
            .ok_or(value)
    }
}

impl TryFrom<&str> for Command {
    type Error = &'static str;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        crate::command_names::command(value).ok_or("unknown divoom command name")
    }
}

// The tests live in a sibling file: they are hand-written and these three
// are generated, so a test module in here would be erased by the next
// regeneration -- a test that stops running without ever failing.
#[cfg(test)]
#[path = "command_model_tests.rs"]
mod tests;
