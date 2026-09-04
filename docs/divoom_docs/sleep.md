# Sleep

## Get sleep scene (0xa2)

**URL:** https://docin.divoom-gz.com/web/#/5/266

**Content Length:** 808 characters

Welcome to the Divoom API

command description
This command is used to get the current scene mode settings from the device.
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0xa2	xx	0x02

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0xa2	0x55	data[]	xx	0x02

data[]:

uint8 time: The time of the scene mode.
uint8 mode: The scene mode type.
uint8 on: The on/off status of the scene mode.
uint8 fm_freq[2]: The FM frequency settings for the scene mode (2 bytes).
uint8 volume: The volume level for the scene mode.
uint8 color_r: The red color component value for the scene mode.
uint8 color_g: The green color component value for the scene mode.
uint8 color_b: The blue color component value for the scene mode.
uint8 light: The light settings for the scene mode.

---

## Set sleep scene listen (0xa3)

**URL:** https://docin.divoom-gz.com/web/#/5/272

**Content Length:** 470 characters

Welcome to the Divoom API

command description
This command is used to set the sleep mode listen settings. It allows the app to control the sleep mode listen feature.
Head	Len	Cmd	data	Checksum	Tail
0x01	xx (2 bytes)	0xa3	data[]	xx	0x02

Data Format:

uint8 on_off: The on/off status of the sleep mode listen feature. 1 means “on” and 0 means “off”.
uint8 mode: The mode of the sleep mode listen feature.
uint8 volume: The volume level for the sleep mode listen feature.

---

## Set scene vol (0xa4)

**URL:** https://docin.divoom-gz.com/web/#/5/273

**Content Length:** 308 characters

Welcome to the Divoom API

command description
This command is used to set the volume level for the sleep mode listen feature.
Head	Len	Cmd	Volume	Checksum	Tail
0x01	xx (2 bytes)	0xa4	Volume	xx	0x02

uint8 volume: Represents the volume level at which the alarm audition will be played, ranging from 0 to 100.

---

## Set sleep color (0xad)

**URL:** https://docin.divoom-gz.com/web/#/5/274

**Content Length:** 452 characters

Welcome to the Divoom API

command description
This command is used to set the sleep mode color. When adjusting the color using the color bar, this command is used.
Head	Len	Cmd	color	Checksum	Tail
0x01	xx (2 bytes)	0xad	color[]	xx	0x02

The color format for this command is as follows:

uint8 color_r: Red component of the sleep mode color.
uint8 color_g: Green component of the sleep mode color.
uint8 color_b: Blue component of the sleep mode color.

---

## Set sleep light (0xae)

**URL:** https://docin.divoom-gz.com/web/#/5/275

**Content Length:** 529 characters

Welcome to the Divoom API

command description
This command is used to set the sleep mode brightness. When adjusting the brightness using the brightness bar, this command is used.
Head	Len	Cmd	light	Checksum	Tail
0x01	xx (2 bytes)	0xae	light	xx	0x02

The light format for this command is as follows:

uint8 light: The brightness level for the sleep mode. The value of light can range from 0 to 255, representing the intensity of the brightness. A higher value means a brighter display, while a lower value means a dimmer display.

---

## Set sleep auto off (0x40)

**URL:** https://docin.divoom-gz.com/web/#/5/276

**Content Length:** 636 characters

Welcome to the Divoom API

command description
This command is used to set the auto-off time for the sleep mode.
Head	Len	Cmd	data	Checksum	Tail
0x01	xx (2 bytes)	0x40	data[]	xx	0x02

the data format for this command is as follows:

uint8 time: The duration of the sleep mode in minutes.
uint8 mode: The mode of the sleep mode.
uint8 on: The on/off state of the sleep mode.
uint8 fm_freq[2]: The FM frequency value (2 bytes).
uint8 volume: The volume level.
uint8 color_r: The red component of the color.
uint8 color_g: The green component of the color.
uint8 color_b: The blue component of the color.
uint8 light: The brightness level.

---

## Set sleep scene (0x41)

**URL:** https://docin.divoom-gz.com/web/#/5/277

**Content Length:** 732 characters

Welcome to the Divoom API

command description
This command is used to set the scene mode, including the sleep mode.
Head	Len	Cmd	data	Checksum	Tail
0x01	xx (2 bytes)	0x41	data[]	xx	0x02

Set the scene mode without a time parameter.

the data format for this command is as follows:

uint8 time: The duration of the sleep mode in minutes (in this case, the time is invalid as it has no effect).
uint8 mode: The mode of the scene.
uint8 on: The on/off state of the scene.
uint8 fm_freq[2]: The FM frequency value (2 bytes).
uint8 volume: The volume level.
uint8 color_r: The red component of the color.
uint8 color_g: The green component of the color.
uint8 color_b: The blue component of the color.
uint8 light: The brightness level.

---

