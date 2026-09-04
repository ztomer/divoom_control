# System Settings

## Set brightness（0x74）

**URL:** https://docin.divoom-gz.com/web/#/5/147

**Content Length:** 229 characters

Welcome to the Divoom API

command description
it will set the device brightness.
Head	Len	Cmd	Bright	Checksum	Tail
0x01	xx (2 bytes)	0x74	0~100	xx	0x02

Bright: One byte representing the system brightness, ranging from 0 to 100.

---

## Set work mode (0x5)

**URL:** https://docin.divoom-gz.com/web/#/5/178

**Content Length:** 596 characters

Welcome to the Divoom API

command description
Switch system working mode
Head	Len	Cmd	Mode	Checksum	Tail
0x01	xx (2 bytes)	0x5	mode	xx	0x02

mode:
SPP_DEFINE_MODE_BT = 0, //Blue
SPP_DEFINE_MODE_FM = 1, //FM
SPP_DEFINE_MODE_LINEIN = 2, //LineIn
SPP_DEFINE_MODE_SD = 3, //SD Card play
SPP_DEFINE_MODE_USBHOST = 4, //USB HOST
SPP_DEFINE_MODE_RECORD = 5, //Record
SPP_DEFINE_MODE_RECORDPLAY = 6, //RecordPlay
SPP_DEFINE_MODE_UAC = 7, //uac
SPP_DEFINE_MODE_PHONE = 8, //phone
SPP_DEFINE_MODE_DIVOOM_SHOW = 9, //DIVOOM_SHOW
SPP_DEFINE_MODE_ALARM_SET = 10, //Alarm set
SPP_DEFINE_MODE_GAME = 11, //Game

---

## Get working mode (0x13)

**URL:** https://docin.divoom-gz.com/web/#/5/179

**Content Length:** 282 characters

Welcome to the Divoom API

command description
Get the current system working mode
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x13	xx	0x02

The speaker returns data of the same type as SPP_CHANGE_MODE.

Head	Len	MainCmd	Cmd	mode	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x13	xx	xx	0x02

---

## Send sd status (0x15)

**URL:** https://docin.divoom-gz.com/web/#/5/180

**Content Length:** 443 characters

Welcome to the Divoom API

command description
Notify that there is an insertion or removal action on the TF card
Head	Len	MainCmd	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x15	xx	0x02
To obtain the TF card status, send this command, and the device will also actively report the TF card status
Head	Len	MainCmd	Cmd	AckCode	Status	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x15	0x55	status	xx	0x02

Status: 1 for insertion status, 0 for removal status

---

## Set boot gif (0x52)

**URL:** https://docin.divoom-gz.com/web/#/5/181

**Content Length:** 692 characters

Welcome to the Divoom API

command description
Command to set the boot animation
The format of the command packet for setting the alarm animation is similar to SPP_SET_ALARM_TIME_GIF, with an additional switch:
Head	Len	Cmd	On_Off	Tol	id	data[]	Checksum	Tail
0x01	xx (2 bytes)	0x52	on_off	tol	id	data[]	xx	0x02

On_off: one tytes 1 set 0 not set
Tol_len: Occupies two bytes, representing the total length of the entire data.

id: Occupies one byte, representing the sequence number of the sent data.

data[]: This field contains the following structure: divoom_image_encode_encode_pic encoded data. The data is fixed at 200 bytes, and for the last packet, the actual data size is transmitted.

---

## Get device temp (0x59)

**URL:** https://docin.divoom-gz.com/web/#/5/182

**Content Length:** 491 characters

Welcome to the Divoom API

command description
Get the device’s temperature
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x59	xx	0x02

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x59	0x55	data[]	xx	0x02

The format of the DATA field is as follows:

The first byte indicates the temperature format of the device:

1: Fahrenheit
0: Celsius

The second byte represents the temperature value:

data[1] = temp_value; Temperature, signed value.

---

## Send net temp (0x5d)

**URL:** https://docin.divoom-gz.com/web/#/5/183

**Content Length:** 689 characters

Welcome to the Divoom API

command description
send the temperature
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0x5d	data[]	xx	0x02

The app sends this command to the device when there is a change in temperature.
Data: The format of the data is as follows:

Year: data[0] = year & 0xFF; data[1] = year >> 8; (Year)

Mon: data[2] = mon; (Month)

Day: data[3] = day; (Day)

Hour: data[4] = hour; (Hour)

Min: data[5] = min; (Minute)

Num: data[6] = num; (Number of data sets)

DATA information: The following data consists of “num” sets of weather information, where each set occupies 2 bytes: the first byte represents the temperature, and the second byte represents the weather type.

---

## Send net temp disp (0x5e)

**URL:** https://docin.divoom-gz.com/web/#/5/184

**Content Length:** 438 characters

Welcome to the Divoom API

command description
Command to send network temperature display
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0x5E	data[]	xx	0x02

Data: The format of the data is as follows:

data[0~4]: Display modes. If selected, it is set to 1; otherwise, it is set to 0. Time must also be included.

Data[5] = time_min & 0xFF; time_second is the number of minutes since 00:00 of the current day.

Data[6] = time_min >> 8

---

## Send current temp (0x5f)

**URL:** https://docin.divoom-gz.com/web/#/5/185

**Content Length:** 252 characters

Welcome to the Divoom API

command description
Command to send current temperature and weather
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0x5F	data[]	xx	0x02

Data:
Data[0]: Temperature value, can be negative (char type).

Data[1]: Weather type.

---

## Get net temp disp (0x73)

**URL:** https://docin.divoom-gz.com/web/#/5/186

**Content Length:** 562 characters

Welcome to the Divoom API

command description
Command to obtain the network temperature display mode
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x73	xx	0x02

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x73	0x55	data[]	xx	0x02

Data: The format of the data is as follows:
data[0~4]: Display modes. If selected, it is set to 1; otherwise, it is set to 0. Time must also be included.
Data[5] = time_second & 0xFF; time_second is the number of minutes since 00:00 of the current day.
Data[6] = time_second >> 8

---

## Set device name (0x75)

**URL:** https://docin.divoom-gz.com/web/#/5/187

**Content Length:** 531 characters

Welcome to the Divoom API

command description
Command to modify the Bluetooth device name
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0x75	data	xx	0x02

Data: The data format is as follows:

Length (one byte) + Device name in UTF-8 format (excluding “Tivoo-audio”). The maximum length of the name is 16 characters. If a length of 0 is sent, the device name will be restored to the default name (“Tivoo-audio” or “Tivoo-light”).

To modify the device name to “Tivoo-audio-aaa”, only send “aaa” as the data with a length of 3.

---

## Get device name (0x76)

**URL:** https://docin.divoom-gz.com/web/#/5/188

**Content Length:** 379 characters

Welcome to the Divoom API

command description
Command to obtain the Bluetooth device name
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x76	xx	0x02

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x76	0x55	data	xx	0x02

Data: The data format is as follows:

Length (one byte) + Device name in UTF-8 format (excluding “TIMEBOX+”).

---

## Set low power switch (0xb2)

**URL:** https://docin.divoom-gz.com/web/#/5/189

**Content Length:** 232 characters

Welcome to the Divoom API

command description
Command to switch low power mode
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0xb2	data	xx	0x02

Data: data[0], where:

1: Turn on the low power mode
0: Turn off the low power mode

---

## Get low power switch (0xb3)

**URL:** https://docin.divoom-gz.com/web/#/5/190

**Content Length:** 348 characters

Welcome to the Divoom API

command description
Command to obtain the low power mode switch status
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0xb3	xx	0x02

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0xb3	0x55	data	xx	0x02

Data: data[0], where:

1: Low power mode is on
0: Low power mode is off

---

## Set temp type (0x2b)

**URL:** https://docin.divoom-gz.com/web/#/5/191

**Content Length:** 540 characters

Welcome to the Divoom API

command description
Command to set the temperature format
Head	Len	Cmd	Type	Checksum	Tail
0x01	xx (2 bytes)	0x2b	type	xx	0x02

Type: One byte representing the temperature format:

1: Fahrenheit
0: Celsius
0xFF: Get the device configuration (query the current temperature format) Only this type device need response

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x2b	0x55	data	xx	0x02

Data: One byte representing the temperature format:

1: Fahrenheit
0: Celsius

---

## Set hour type (0x2c)

**URL:** https://docin.divoom-gz.com/web/#/5/192

**Content Length:** 534 characters

Welcome to the Divoom API

command description
Command to set the hour format
Head	Len	Cmd	Type	Checksum	Tail
0x01	xx (2 bytes)	0x2c	type	xx	0x02

Type: One byte representing the hour format:

0: 12-hour format
1: 24-hour format
0xFF: Get the device configuration (query the current hour format) Only this type device need response

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Type	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x2c	0x55	Type	xx	0x02

Type: One byte representing the hour format:

0: 12-hour format
1: 24-hour format

---

## Set song dis ctrl (0x83)

**URL:** https://docin.divoom-gz.com/web/#/5/193

**Content Length:** 617 characters

Welcome to the Divoom API

command description
Command to set the song name display switch
Head	Len	Cmd	Type	Checksum	Tail
0x01	xx (2 bytes)	0x83	ctrl	xx	0x02

Ctrl: One byte representing the control for the song name display switch:

0: Turn off (disable)
1: Turn on (enable)
0xFF: Get the current configuration (query the current status)

Device response command:

Head	Len	MainCmd	Cmd	AckCode	ctrl	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x83	0x55	ctrl	xx	0x02

Ctrl: One byte representing the status of the song name display switch:

0: Display switch is turned off (disabled)
1: Display switch is turned on (enabled)

---

## Set blue password (0x27)

**URL:** https://docin.divoom-gz.com/web/#/5/194

**Content Length:** 726 characters

Welcome to the Divoom API

command description
Command to set the password for user’s Bluetooth connection
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0x27	data[]	xx	0x02

APP sends data to the device as follows:

Control: 1 byte

1: Set a new password
0: Cancel the password
2: Get password setting status

Password: 4 bytes

Valid only when the control byte is 1, represents the new four-digit password.

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x27	0x55	data	xx	0x02

The device sends data to the APP as follows:

Password Setting Status: 1 byte

0: Password is not set
1: Password is set

Password Information: 4 bytes

Available only when the password is set.

---

## Set poweron voice vol (0xbb)

**URL:** https://docin.divoom-gz.com/web/#/5/195

**Content Length:** 649 characters

Welcome to the Divoom API

command description
Command to set or get the power-on voice volume
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0xbb	data[]	xx	0x02

APP sends data to the device as follows:

Control Field data[0]: 1 byte

1: Set the power-on voice volume
0: Get the current power-on voice volume

Volume Size data[1]: 1 byte

Represents the volume level ranging from 0 to 100.

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0xbb	0x55	data	xx	0x02

The device sends data to the APP as follows:

Volume Size: 1 byte

Represents the current power-on voice volume ranging from 0 to 100.

---

## Set poweron channel (0x8a)

**URL:** https://docin.divoom-gz.com/web/#/5/196

**Content Length:** 685 characters

Welcome to the Divoom API

command description
Command to set the power-on channel.
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0x8a	data[]	xx	0x02

APP sends data to the device as follows:

Control Field data[0]: 1 byte

1: Set the power-on channel
0: Get the current power-on channel

Channel ID data[1]: 1 byte

0: Time face
1: Nightlight
2: Cloud channel
3: VJ lighting effects
4: Music EQ
5: Custom

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x8a	0x55	data	xx	0x02

The device sends data to the APP as follows:

Current Set Channel ID: 1 byte

Represents the current power-on channel based on the values mentioned above.

---

## Set auto power off (0xab)

**URL:** https://docin.divoom-gz.com/web/#/5/197

**Content Length:** 263 characters

Welcome to the Divoom API

command description
Command to set the auto power-off timer
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0xab	data	xx	0x02

data: 2 bytes (minutes), little-endian format
For example, 720 minutes (0x2D0), byte[0]=0xD0, byte[1]=0x02;

---

## Get auto power off (0xac)

**URL:** https://docin.divoom-gz.com/web/#/5/198

**Content Length:** 381 characters

Welcome to the Divoom API

command description
Command to get the current auto power-off timer
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0xac	xx	0x02

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0xac	0x55	data	xx	0x02

Data: 2 bytes (minutes), little-endian format
For example, 720 minutes (0x2D0), byte[0]=0xD0, byte[1]=0x02;

---

## Set sound ctrl (0xa7)

**URL:** https://docin.divoom-gz.com/web/#/5/314

**Content Length:** 303 characters

Welcome to the Divoom API

command description
Command to Control screen switch with ambient sound
Head	Len	Cmd	data	Checksum	Tail
0x01	xx (2 bytes)	0xa7	data (1 bytes)	xx	0x02

data format:

1: Enables the screen to be controlled by ambient sound
0: Disable the screen to be controlled by ambient sound

---

## Get sound ctrl (0xa8)

**URL:** https://docin.divoom-gz.com/web/#/5/315

**Content Length:** 422 characters

Welcome to the Divoom API

command description
Command to returns the sound control switch value from device
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0xa8	xx	0x02

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0xa8	0x55	data(1 bytes)	xx	0x02

data format:

1: Enables the screen to be controlled by ambient sound
0: Disable the screen to be controlled by ambient sound

---

