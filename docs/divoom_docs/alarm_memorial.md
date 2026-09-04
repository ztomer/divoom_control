# Alarm Memorial

## Get alarm time (0x42)

**URL:** https://docin.divoom-gz.com/web/#/5/246

**Content Length:** 473 characters

Welcome to the Divoom API

command description
Request to get the extended alarm time information from the device.
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x42	xx	0x02

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x42	0x55	data[]x10	xx	0x02

Data[] format is the same as the one used in SPP_SET_ALARM_TIME_EXT2 command (excluding the animation data). The device will provide 10 sets of alarm information in response.

---

## Set alarm time (0x43)

**URL:** https://docin.divoom-gz.com/web/#/5/247

**Content Length:** 920 characters

Welcome to the Divoom API

command description
Set the extended alarm time information in the device.
Head	Len	Cmd	data	Checksum	Tail
0x01	xx (2 bytes)	0x43	data[]	xx	0x02

Use this command to set the extended alarm time information in the device. The command includes the following data format:

Uint8 alarm_index: Indicates which alarm to set, starting from 0.
Uint8 status: 1 (alarm on), 0 (alarm off).
Uint8 hour: Hour to set for the alarm.
Uint8 minute: Minute to set for the alarm.
Uint8 week: Bits 0 to 6 represent Sunday to Saturday, respectively. Set to 1 if the alarm should repeat on that day.
Uint8 mode: Alarm mode (ALARM_MUSIC=0, and others: 1, 2, 3, 4).
Uint8 trigger_mode: Alarm trigger mode (ALARM_TRIGGER_MUSIC=1, ALARM_TRIGGER_GIF=4).
Uint8 Fm[2]: If the trigger mode is ALARM_TRIGGER_MUSIC, these 2 bytes represent the frequency point.
Uint8 volume: Volume level for the alarm, ranging from 0 to 100.

---

## Set alarm gif (0x51)

**URL:** https://docin.divoom-gz.com/web/#/5/248

**Content Length:** 1210 characters

Welcome to the Divoom API

command description
This command is used to set the alarm animation for a specific alarm.
Head	Len	Cmd	Alarm index	Tol len	id	data	Checksum	Tail
0x01	xx (2 bytes)	0x51	data[]	xx (2 bytes)	xx(1 bytes)	data[]	xx	0x02

Data Format:

Tol_len: 2 bytes, the total length of the data packet.
id: 1 byte, the sequence number of the data packet.
data[]: The data array containing the encoded animation data using the divoom_image_encode_encode_pic format. The size of the data array is fixed to 200 bytes, but the actual data size can be less for the last packet.

Other Parameter:

alarm_index: 1 byte, representing the index of the alarm for which the animation is being set.

The command allows the app to set a custom animation for a specific alarm. The animation data should be encoded using the divoom_image_encode_encode_pic format, and the app can send multiple packets of animation data, with the sequence number (id) used to distinguish between different packets. The size of the animation data is specified in the Tol_len field.

Note that this command should be sent after setting the alarm time and other alarm-related parameters to associate the animation with a specific alarm.

---

## Set memorial time (0x54)

**URL:** https://docin.divoom-gz.com/web/#/5/249

**Content Length:** 717 characters

Welcome to the Divoom API

command description
Set the extended daily time information on the device.
Head	Len	Cmd	data	Checksum	Tail
0x01	xx (2 bytes)	0x54	data[]	xx	0x02

Use this command to set the extended daily time information on the device. The Data[] field contains the information for a single daily time record, and the format is as follows:

Uint8 DialyID: Record identifier, corresponds to the index 0, 1, 2.
Uint8 on_off: Switch flag; 1 for on, 0 for empty record.
Uint8 month: Month (1 byte).
Uint8 day: Day (1 byte).
Uint8 hour: Hour (1 byte).
Uint8 minute: Minute (1 byte).
Uint8 have_flag: Whether there is an animation; 0 for no, 1 for yes.
Uint8 titile_name[32]: Name of the record, using 32 bytes.

---

## Get memorial time (0x53)

**URL:** https://docin.divoom-gz.com/web/#/5/250

**Content Length:** 734 characters

Welcome to the Divoom API

command description
Set the extended daily time information on the device.
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x53	xx	0x02

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x53	0x55	data[]x10	xx	0x02

The data[] is an array of 10 daily time records, each in the following format:

Uint8 DialyID: Record identifier, corresponds to the index 0, 1, 2,… 9.
Uint8 on_off: Switch flag; 1 for on, 0 for empty record.
Uint8 month: Month (1 byte).
Uint8 day: Day (1 byte).
Uint8 hour: Hour (1 byte).
Uint8 minute: Minute (1 byte).
Uint8 have_flag: Whether there is an animation; 0 for no, 1 for yes.
Uint8 titile_name[32]: Name of the record, using 32 bytes.

---

## Set memorial gif (0x55)

**URL:** https://docin.divoom-gz.com/web/#/5/251

**Content Length:** 707 characters

Welcome to the Divoom API

command description
This command is used to set the alarm animation for a specific alarm.
Head	Len	Cmd	Memorial index	Tol len	id	data	Checksum	Tail
0x01	xx (2 bytes)	0x55	xx (1 bytes)	xx (2 bytes)	xx(1 bytes)	data[]	xx	0x02

Data Format:

Tol_len: 2 bytes, the total length of the data packet.
id: 1 byte, the sequence number of the data packet.
data[]: The data array containing the encoded animation data using the divoom_image_encode_encode_pic format. The size of the data array is fixed to 200 bytes, but the actual data size can be less for the last packet.

Other Parameter:

memorial_index: 1 byte, representing the index of the alarm for which the animation is being set.

---

## Set alarm listen (0xa5)

**URL:** https://docin.divoom-gz.com/web/#/5/252

**Content Length:** 635 characters

Welcome to the Divoom API

command description
Alarm audition command

This command is used to enable or disable the alarm audition feature, where the alarm sound can be played briefly to give the user an idea of what it will sound like. The packet format is as follows:

Head	Len	Cmd	data	Checksum	Tail
0x01	xx (2 bytes)	0xa5	data[]	xx	0x02

Data Format:
uint8 on_off: Represents the on/off status of the alarm audition feature. 1 means it is enabled, and 0 means it is disabled.
uint8 mode: Represents the mode of the alarm sound.
uint8 volume: Represents the volume level at which the audition will be played, ranging from 0 to 100.

---

## Set alarm vol (0xa6)

**URL:** https://docin.divoom-gz.com/web/#/5/253

**Content Length:** 374 characters

Welcome to the Divoom API

command description
Set Alarm Audition Volume command

This command is used to set the volume level for the alarm audition feature. The packet format is as follows:

Head	Len	Cmd	Volume	Checksum	Tail
0x01	xx (2 bytes)	0xa6	Volume	xx	0x02

uint8 volume: Represents the volume level at which the alarm audition will be played, ranging from 0 to 100.

---

## Set alarm vol ctrl (0x82)

**URL:** https://docin.divoom-gz.com/web/#/5/254

**Content Length:** 634 characters

Welcome to the Divoom API

command description
Alarm Voice Control command

This command is used to control the voice alarm feature. The packet format is as follows:

Head	Len	Cmd	ctrl	index	Checksum	Tail
0x01	xx (2 bytes)	0x82	ctrl	index	xx	0x02

uint8 Ctrl: Represents the control action for the voice alarm.

0: Start recording for voice alarm.
1: Start playing the recorded voice alarm.
2: Stop playing the recorded voice alarm.

uint8 Index: Represents the index of the alarm for which the voice alarm action should be applied.

Device Response:

Head	Len	MainCmd	Cmd	AckCode	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x82	0x55	xx	0x02

---

