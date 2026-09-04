# Music Play

## get sd play name (0x6)

**URL:** https://docin.divoom-gz.com/web/#/5/199

**Content Length:** 518 characters

Welcome to the Divoom API

command description
Command to display the current sd card music playing name
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x6	xx	0x02

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Name len	Name	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x6	0x55	name len	name	xx	0x02

Name Length: 2 bytes (representing the length of the name in bytes, not Unicode length)

The maximum name length on the device side is 128 bytes, and the length is not in Unicode format.
The name is encoded in Unicode.

---

## Get sd music list (0x7)

**URL:** https://docin.divoom-gz.com/web/#/5/200

**Content Length:** 1010 characters

Welcome to the Divoom API

command description
Command to get the playlist
Head	Len	Cmd	Start id	End id	Checksum	Tail
0x01	xx (2 bytes)	0x7	xx (2 bytes)	xx (2 bytes)	xx	0x02
When requesting the playlist, send the start music ID and end music ID, each represented by two bytes (little-endian format, lower byte first, higher byte later). If needed, first send the command to get the total length: SPP_GET_SD_MUSIC_LIST_TOTAL_NUM = 0x7D.

Device respond:

Head	Len	Response Cmd	Cmd	AckCode	Music id	Name len	Name	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x7	0x55	xx (2 bytes)	xx (2 bytes)	xx	xx	0x02
Music ID: 2 bytes, represents the song ID, starting from 0 (little-endian format, lower byte first, higher byte later).
Name Length: 2 bytes (normal length, not Unicode length, little-endian format, lower byte first, higher byte later).
Name: Encoded in Unicode. For example, “果” -> “\u679c” (Unicode), data sending format: 679c.

After the list is returned, the device returns a SPP_SEND_SD_LIST_OVER = 0x14 command.

---

## Set vol (0x8)

**URL:** https://docin.divoom-gz.com/web/#/5/201

**Content Length:** 190 characters

Welcome to the Divoom API

command description
Command to set the volume
Head	Len	Cmd	Vol	Checksum	Tail
0x01	xx (2 bytes)	0x8	xx (0~15)	xx	0x02

Vol: 0 to 15 (representing the volume level).

---

## Get vol (0x9)

**URL:** https://docin.divoom-gz.com/web/#/5/202

**Content Length:** 316 characters

Welcome to the Divoom API

command description
Command to get the current volume
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x9	xx	0x02

The device responds with:

Head	Len	MainCmd	Cmd	AckCode	Vol	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x9	0x55	xx (0~15)	xx	0x02

Vol: 0 to 15 (representing the current volume level).

---

## Set play status (0xa)

**URL:** https://docin.divoom-gz.com/web/#/5/203

**Content Length:** 179 characters

Welcome to the Divoom API

command description

-Command to set the current play status.

Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0xa	xx	xx	0x02

Data: Pause: 0, Play: 1

---

## Get play status (0xb)

**URL:** https://docin.divoom-gz.com/web/#/5/204

**Content Length:** 390 characters

Welcome to the Divoom API

command description
Command to set the current play status.
The format of the command packet for setting the alarm animation is similar to SPP_SET_ALARM_TIME_GIF, with an additional switch:
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0xb	xx	0x02
Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0xb	0x55	data	xx	0x02

Data: Pause: 0, Play: 1

---

## Set sd play music id (0x11)

**URL:** https://docin.divoom-gz.com/web/#/5/205

**Content Length:** 369 characters

Welcome to the Divoom API

command description
Command to set the current playing song
Head	Len	Cmd	Music id	Checksum	Tail
0x01	xx (2 bytes)	0x11	xx (2 bytes)	xx	0x02

MusicId: Two bytes representing the song ID, based on the playlist obtained earlier.

Set Ok Device response command:

Head	Len	MainCmd	Cmd	Ackcode	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x11	0x55	xx	0x02

---

## Set sd last next (0x12)

**URL:** https://docin.divoom-gz.com/web/#/5/206

**Content Length:** 224 characters

Welcome to the Divoom API

command description
Command to control the previous or next track for both FM and music.
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0x12	data	xx	0x02

Data: Previous track: 0, Next track: 1.

---

## Send sd list over (0x14)

**URL:** https://docin.divoom-gz.com/web/#/5/207

**Content Length:** 292 characters

Welcome to the Divoom API

command description
Command to notify that the playlist has been fully sent.
Head	Len	Maincmd	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x14	xx	0x02

Data: The format of the data is as follows:

This command is sent after the playlist has been completely transmitted.

---

## Get sd music list total num (0x7d)

**URL:** https://docin.divoom-gz.com/web/#/5/208

**Content Length:** 372 characters

Welcome to the Divoom API

command description
Command for the app to get the total number of music tracks on the SD card.
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x7d	xx	0x02

Device response:

Head	Len	MainCmd	Cmd	AckCode	Total num	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x7d	0x55	total num (2bytes)	xx	0x02

Total Num: The total number of music tracks on the SD card.

---

## Get sd music info (0xb4)

**URL:** https://docin.divoom-gz.com/web/#/5/209

**Content Length:** 861 characters

Welcome to the Divoom API

command description
Command for the app to get the SD card music playback information.
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0xb4	xx	0x02

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0xb4	0x55	data[]	xx	0x02

DATA data format:
{
uint16_t cur_time; // Current playback time, little-endian, unit: seconds
uint16_t total_time; // Total time of the current song, little-endian, unit: seconds
uint16_t music_id; // Current music ID for each region
uint8_t status; // Current playback status: 0 for pause, 1 for play
uint8_t vol; // Volume: 0~15
uint8_t play_mode; // Current playback mode (refer to SPP_SET_SD_MUSIC_PLAY_MODE)
// 1: List Loop, 2: Single Loop, 3: Shuffle Play
}

The values are represented in little-endian format, with the low byte first and the high byte second.

---

## Set sd music info (0xb5)

**URL:** https://docin.divoom-gz.com/web/#/5/210

**Content Length:** 661 characters

Welcome to the Divoom API

command description
Command for the app to set the SD card music playback information.
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0xb5	data	xx	0x02

DATA data format:
{
uint16_t cur_time; // Current playback time, little-endian
uint16_t music_id; // Current music ID for the song, little-endian
uint8_t vol; // Volume: 0~15
uint8_t status; // Current playback status: 0 for pause, 1 for play
uint8_t play_mode; // Current playback mode (refer to SPP_SET_SD_MUSIC_PLAY_MODE)
// 1: List Loop, 2: Single Loop, 3: Shuffle Play
}

The values are represented in little-endian format, with the low byte first and the high byte second.

---

## Set sd music postion (0xb8)

**URL:** https://docin.divoom-gz.com/web/#/5/211

**Content Length:** 340 characters

Welcome to the Divoom API

command description
Command for the app to set the SD card music playback position.
Head	Len	Cmd	Postion	Checksum	Tail
0x01	xx (2 bytes)	0xb8	xx (2 bytes)	xx	0x02

Position: The position to set, represented in seconds. The value should be in little-endian format, with the low byte first and the high byte second.

---

## Set sd music play mode (0xb9)

**URL:** https://docin.divoom-gz.com/web/#/5/212

**Content Length:** 329 characters

Welcome to the Divoom API

command description
Command for the app to set the current playback mode of SD card music.
Head	Len	Cmd	Play mode	Checksum	Tail
0x01	xx (2 bytes)	0xb9	data (1 bytes)	xx	0x02

Play mode: The desired playback mode.
1: List loop
2: Single loop
3: Random play
Note: The “Play mode” field is 1 byte in size.

---

## App need get music list (0x47)

**URL:** https://docin.divoom-gz.com/web/#/5/213

**Content Length:** 341 characters

Welcome to the Divoom API

command description

-The app requests to get the music playlist.

Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x47	xx	0x02

When the app needs the playlist, it sends this command to the device. The device will reply to this command with the music playlist when it is ready. There is no data payload in the reply.

---

## Send sd card status (0x15)

**URL:** https://docin.divoom-gz.com/web/#/5/214

**Content Length:** 568 characters

Welcome to the Divoom API

command description
device Notify the TF (microSD) card insertion or removal to app.
Head	Len	Maincmd	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x15	xx	0x02

Use this command to notify the device about the insertion or removal of the TF (microSD) card. When the app sends this command, the device will also actively send the TF card status.

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Status	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x15	0x55	status (1 bytes)	xx	0x02

Status: 1 indicates TF card insertion, 0 indicates TF card removal.

---

## Page 17

**URL:** https://docin.divoom-gz.com/web/#/5/215

**Content Length:** 5825 characters

Contact Divoom command format Find device DIY Net Data Clock 
        PIXOO64
        System reboots 
        dial control
        Dial Type Dial List Select faces Channel Get select face id 
        channel control
        select channel control custom channel Visualizer Channel Cloud Channel get cureent channel 
        system setting
        set brightness get all setting Weather area setting Set Time Zone  system Time Screen switch Get Device Time Set temperature mode Set  Rotation angle Set  Mirror mode Set  hour mode Set  High Ligit mode Set  White Balance Get the Weather  of the device SetGalleryTime Set Subscribe Gallery attribute 
        tool
        Set countdown tool Set stopwatch tool Set scoreboard tool Set noise tool 
        animation function
        play gif Get  sending animation PicId  Reset  sending animation PicId Send animation Send Text Clear all text area Get font list Send display list  Play Buzzer play divoom gif Get Img Upload List Get My Like Img List save gif Play a frame of a GIF file 
        Command list
        Command list Url Command file 
        PIXOO16
        
        system setting
        set brightness get all setting Weather area setting Set Time Zone  system Time Screen switch Get Device Time Set temperature mode Set  Rotation angle Set  hour mode Set  Mirror mode Get the Weather  of the device 
        channel control
        select channel control custom channel Visualizer Channel Cloud Channel get cureent channel 
        animation control
        play gif Get  sending animation PicId  Reset  sending animation PicId Send animation Play Buzzer play divoom gif Get Img Upload List Get My Like Img List 
        tool
        Set countdown tool Set stopwatch tool Set scoreboard tool Set noise tool 
        dial control
        Dial Type Dial List Select faces Channel Get select face id 
        command list
        
        TimeGate
        System reboots 
        system setting
        set brightness get all setting Weather area setting Set Time Zone  system Time Screen switch Get Device Time Set temperature mode Set  Mirror mode Set  hour mode Get the Weather  of the device SetGalleryTime Set RGB Information 
        dial control
        Sub Dial Type Indeividual Dial List get whole dial List Select  Whole Dial Select  Channel Type Get  Channel Information Select Indeividual dial Select Indeividual Visualizer Channel 
        tool
        Set countdown tool Set stopwatch tool Set scoreboard tool Set noise tool Play Buzzer 
        animation function
        Get My Like Img List Get Img Upload List play divoom gif play gif play gif in all gif Send animation Send Text Clear text area Get font list Send display list  
        Command list
        Command list Url Command file 
        Bluetooth(tivoo,timebox,pixoo,backpack)
        Protocol introduction 
        system setting
        Set brightness（0x74） Set work mode (0x5) Get working mode (0x13) Send sd status (0x15) Set boot gif (0x52) Get device temp (0x59) Send net temp (0x5d) Send net temp disp (0x5e) Send current temp (0x5f) Get net temp disp (0x73) Set device name (0x75) Get device name (0x76) Set low power switch (0xb2) Get low power switch (0xb3) Set temp type (0x2b) Set hour type (0x2c) Set song dis ctrl (0x83) Set blue password (0x27) Set poweron voice vol (0xbb) Set poweron channel (0x8a) Set auto power off (0xab) Get auto power off (0xac) Set sound ctrl (0xa7) Get sound ctrl (0xa8) 
        music play
        get sd play name (0x6) Get sd music list (0x7) Set vol (0x8) Get vol (0x9) Set play status (0xa) Get play status (0xb) Set sd play music id (0x11) Set sd last next (0x12) Send sd list over (0x14) Get sd music list total num (0x7d) Get sd music info (0xb4) Set sd music info (0xb5) Set sd music postion (0xb8) Set sd music play mode (0xb9) App need get music list (0x47) Send sd card status (0x15) 
        alarm memorial
        Get alarm time (0x42) Set alarm time (0x43) Set alarm gif (0x51) Set memorial time (0x54) Get memorial time (0x53) Set memorial gif (0x55) Set alarm listen (0xa5) Set alarm vol (0xa6) Set alarm vol ctrl (0x82) 
        time plan
        Set time manage info (0x56) Set time manage ctrl (0x57) 
        tool
        Get tool info (0x71) Set tool info (0x72) 
        sleep
        Get sleep scene (0xa2) Set sleep scene listen (0xa3) Set scene vol (0xa4) Set sleep color (0xad) Set sleep light (0xae) Set sleep auto off (0x40) Set sleep scene (0x41) 
        game
        Send game shark (0x88) Set game (0xa0) Set game ctrl info (0x17) Set game ctrl key up info (0x21) 
        light
        Set light mode (0x45) Get light mode (0x46) Set light pic (0x44) Set light phone gif (0x49) Set gif speed (0x16) Set light phone word attr (0x87) App new send gif cmd (0x8b) Set user gif (0xb1) Modify user gif items (0xb6) App new user define (0x8c) App big64 user define (0x8d) App get user define info (0x8e) Set rhythm gif (0xb7) App send eq gif (0x1b) Drawing mul pad ctrl (0x3a) Drawing big pad ctrl (0x3b) Drawing pad ctrl (0x58) Drawing pad exit (0x5a) Drawing mul encode single pic (0x5b) Drawing mul encode  pic (0x5c) Drawing mul encode  gif play (0x6b) Drawing encode movie play (0x6c) Drawing mul encode movie play (0x6d) Drawing ctrl movie play (0x6e) Drawing mul pad enter (0x6f) Sand paint ctrl (0x34) Pic scan ctrl (0x35) 
        TimeFrame
        command url System reboots 
        tool
        Set countdown tool Set stopwatch tool Set scoreboard tool Set noise tool 
        system setting
        set brightness Weather area setting Screen switch Set  Mirror mode Set  hour mode 
        dial control
        Dial Type Select faces Channel 
        Custom Control
        Enter custom display mode Exit custom display mode Update Text Content Get font list              Share pageConfirm  History version

---

