# Light

## Set light mode (0x45)

**URL:** https://docin.divoom-gz.com/web/#/5/287

**Content Length:** 1573 characters

Welcome to the Divoom API

command description
This command is used to control the light mode of the device.
Head	Len	Cmd	data	Checksum	Tail
0x01	xx (2 bytes)	0x45	data	xx	0x02

Data Format:

data[0]: Mode, which can take one of the following values:
DIVOOM_DISP_ENV_MODE (0): Environmental mode. The rest of the data fields are used for this mode.
DIVOOM_DISP_LIGHT_MODE (1): Light mode. The rest of the data fields are used for this mode.
DIVOOM_DISP_DIVOOM_MODE (2): Divoom mode. No additional data is used for this mode.
DIVOOM_DISP_SPECIAL_MODE (3): Special mode. The mode selection is specified in data[1].
DIVOOM_DISP_MUISE_MODE (4): Music mode. The mode selection is specified in data[1].
DIVOOM_DISP_USER_DEFINE_MODE (5): User-defined mode. No additional data is used for this mode.

For DIVOOM_DISP_ENV_MODE (0):

data[1]: 12-hour format (0) or 24-hour format (1) for time display (time is not processed, handled in the 0x2C command).
data[2]: Display mode, starting from 0.
data[3-6]: Checkbox values.
data[7-9]: RGB color values.

For DIVOOM_DISP_LIGHT_MODE (1):

data[1-3]: RGB color values.
data[4]: Brightness level.
data[5]: Light effect mode.
data[6]: Light on/off switch.

For DIVOOM_DISP_SPECIAL_MODE (3):

data[1]: Mode selection.

For DIVOOM_DISP_MUISE_MODE (4):

data[1]: Mode selection.

For DIVOOM_DISP_SCORE_MODE (6):

data[1]: 0 (off) or 1 (on).
data[2]: Red score.
data[3]: Blue score.

The command allows the app to set different light modes based on the provided data. The interpretation of data fields depends on the mode specified in data[0].

---

## Get light mode (0x46)

**URL:** https://docin.divoom-gz.com/web/#/5/288

**Content Length:** 1244 characters

Welcome to the Divoom API

command description
This command is used to retrieve the current light mode settings from the device.
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x46	xx	0x02

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x46	0x55	data	xx	0x02

Data Format:

data[0]: Current light effect mode. Possible values are:

0: Clock
1: Night Light
2: HOT
3: VJ
4: Music EQ or Flag (Backpack)
5: Custom
6: Lyric Display

data[1]: Temperature display mode. Fahrenheit is represented by 1, Celsius by 0.

data[2]: VJ selection option.

data[3-5]: RGB color values of the lighting.

data[6]: Brightness level of the lighting.

data[7]: Lighting mode selection option.

data[8]: On/Off switch of the lighting.

data[9]: Music mode selection option.

data[10]: System brightness.

data[11]: Time display format selection option. 12-hour format is represented by 0, and 24-hour format by 1.

data[12-14]: RGB color values of the time display.

data[15]: Time display mode.

data[16-19]: Time checkbox modes.

The device responds with the current settings for different lighting and display options. The values in the data fields indicate the current configurations for the corresponding options.

---

## Set light pic (0x44)

**URL:** https://docin.divoom-gz.com/web/#/5/289

**Content Length:** 534 characters

Welcome to the Divoom API

command description
This command is used to display user-drawn pictures on the device.
Head	Len	Cmd	data	Checksum	Tail
0x01	xx (2 bytes)	0x44	data	xx	0x02

Data: The data field contains the encoded picture data, obtained using the divoom_image_encode_encode_pic function.

With this command, the App can send custom user-drawn pictures to the device, which will then display them according to the encoded data. The picture data must be properly encoded to be correctly interpreted by the device for display.

---

## Set light phone gif (0x49)

**URL:** https://docin.divoom-gz.com/web/#/5/290

**Content Length:** 1070 characters

Welcome to the Divoom API

command description
This command is used to display user-drawn animations on the device.
Head	Len	Cmd	Tol	Id	data	Checksum	Tail
0x01	xx (2 bytes)	0x49	tol (2 bytes)	id (1 bytes)	data[]	xx	0x02

Tol_len: Occupies two bytes and represents the total length of the data.
id: Occupies one byte and represents the sequential number of the sent data.
Data[]: This field contains the encoded animation data, obtained using the divoom_image_encode_encode_pic function. The data size is fixed at 200 bytes for each package, and the last package will carry the actual data size.

Command for the device to upload a file to the App:

Head	Len	MainCmd	Cmd	AckCode	Tol	Id	data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x49	0x55	tol (2 bytes)	id (1 bytes)	data[]	xx	0x02

In this case, the device sends the user-drawn animation file back to the App. The format of the data is the same as described earlier, with Tol_len representing the total length of the data, id representing the sequential number of the data, and Data[] containing the encoded animation data.

---

## Set gif speed (0x16)

**URL:** https://docin.divoom-gz.com/web/#/5/291

**Content Length:** 567 characters

Welcome to the Divoom API

command description
This command is used to modify the animation speed. When the user changes the animation speed on the APP animation page, the APP sends this command to the device.
Head	Len	Cmd	speed	Checksum	Tail
0x01	xx (2 bytes)	0x16	speed	xx	0x02

Speed: Occupies two bytes and represents the animation speed in milliseconds. The speed value is split into two bytes, with data[0] representing the low byte and data[1] representing the high byte. The speed is in milliseconds, and it determines the time delay between animation frames.

---

## Set light phone word attr (0x87)

**URL:** https://docin.divoom-gz.com/web/#/5/292

**Content Length:** 4020 characters

Welcome to the Divoom API

command description
This command is used to set various attributes of the animated text. It consists of several sub-commands with different control values (1, 2, 3, 4, 5, 6, 7), each representing a different attribute change.
Head	Len	Cmd	data	Checksum	Tail
0x01	xx (2 bytes)	0x87	data[]	xx	0x02

The data format for each sub-command is as follows:

Changing Text Speed:

Control (1 byte): 1 (Setting Speed)
Speed (2 bytes): Speed value in milliseconds (little-endian format)
Text Box ID (1 byte): Index of the text box (starting from 0)

Changing Text Effects:

Control (1 byte): 2 (Setting Text Effects)
Effect Style (1 byte): UI arrangement, starting from 0

Changing Text Display Box:

Control (1 byte): 3 (Setting Display Box)
Left-top X coordinate (1 byte): X coordinate of the upper-left corner
Left-top Y coordinate (1 byte): Y coordinate of the upper-left corner
Box Width (1 byte): Width of the display box in terms of points
Box Height (1 byte): Height of the display box in terms of points
Text Box ID (1 byte): Index of the text box (starting from 0)

Changing Text Font:

Control (1 byte): 4 (Setting Font)
Font Size (1 byte): Size of the font in points (16, 24, or 32)
Text Box ID (1 byte): Index of the text box (starting from 0)

Changing Text Color:

Control (1 byte): 5 (Setting Color)
Color Value (3 bytes): RGB color values
Text Box ID (1 byte): Index of the text box (starting from 0)

Changing Text Content:

Control (1 byte): 6 (Setting All Text Information)
Data Length (2 bytes): Length of data (little-endian format)
Data (Variable length): Data containing the text information
Text Box ID (1 byte): Index of the text box (starting from 0)

Changing Image Effects:

Control (1 byte): 7 (Setting Image Effects)
Effect Style (1 byte): UI arrangement, starting from 0
Text Box ID (1 byte): Index of the text box (starting from 0)

For encoding and decoding, the DIVOOM_IMAGE_ENCODE_WORD_INFO structure is used, which contains various parameters for text attributes, font, size, color, effects, and more. The command utilizes divoom_image_encode_frame_word to encode the data before sending it to the device.

The provided code defines data structures used for encoding word information and text in the Divoom image format. Let’s break down the structures and their fields:

DIVOOM_IMAGE_ENCODE_WORD_FONT: This structure represents the font information for a single word.

uint16 unicode16: The Unicode value of the current word.
uint8 font_info[32]: The font’s 16x16 dot matrix information.

DIVOOM_IMAGE_ENCODE_WORD_INFO: This structure contains information about displaying text with specific settings.

uint8 x: The x-coordinate position of the text field.
uint8 y: The y-coordinate position of the text field.
uint8 size: The font size of the text.
uint8 width: The width of the display box.
uint8 high: The height of the display box.
uint8 font_effect: The effect applied to the font.
uint8 pic_effect: The effect applied to the picture.
uint16 speed: The speed of the font.
uint8 color[3]: The RGB color values of the font.
uint16 unicode_len: The length of the Unicode string to be displayed.
uint16 unicode_str[DIVOOM_IMAGE_ENCODE_WORD_MAX_NUM]: The Unicode characters to be displayed.
uint8 word_num: The number of unique characters in unicode_str.
DIVOOM_IMAGE_ENCODE_WORD_FONT font_info[DIVOOM_IMAGE_ENCODE_WORD_MAX_NUM]: An array storing font information for each unique character in unicode_str.

These structures are used in the context of the divoom_image_encode_frame_word function for encoding word data. The purpose of this function is to encode and generate a frame of data that can be sent to a Divoom device to display text with specific settings, effects, and colors.

Please note that the exact behavior and functionality of the Divoom device may depend on its implementation and firmware version. The provided structures and functions are specific to the Divoom image format and may not be directly compatible with other devices or applications.

---

## App new send gif cmd (0x8b)

**URL:** https://docin.divoom-gz.com/web/#/5/293

**Content Length:** 1623 characters

Welcome to the Divoom API

command description
This command is used for the upgrade process to transfer animated data. The data structure for this command varies based on the control word (Control_Word).
Head	Len	Cmd	Control word	Data	Checksum	Tail
0x01	xx (2 bytes)	0x8b	Control_Word	data[]	xx	0x02

Control_Word = 0 (Start Sending):

data[] format:

- File Size (4 bytes): Total size of the file in little-endian format

After sending this command, the APP should wait for the device response before starting to send data.


Device response:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x8b	0x55	data[]	xx	0x02
data[] format:
   - data[0]: Control_Word (1 byte): 0
   - data[1]: Control Data (1 byte):
     - 0: Cannot start, cancel sending
     - 1: Start sending data


Control_Word = 1 (Sending Data):
data[] format:

- File Total Length (4 bytes): Total length of the file in bytes
- File Offset ID (2 bytes): Little-endian value starting from 0
- File Data (256 bytes): Actual data to be sent (up to 256 bytes)


Control_Word = 2 (Terminate Sending):
-no data

Device Requests Resend (Control_Word = 1):

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x8b	0x55	data[]	xx	0x02

data[] format:

data[0]: Control_Word (1 byte): 1
data[1~2] Control Data (2 bytes): Offset value requesting a resend of data

The command is used for transferring animated data from the APP to the device using a control word to manage the process. The data to be sent includes the file size, offset IDs, and actual file data. The device may request a resend of specific data if necessary.

---

## Set user gif (0xb1)

**URL:** https://docin.divoom-gz.com/web/#/5/294

**Content Length:** 1445 characters

Welcome to the Divoom API

command description
This command is used to set a user-defined picture. The data structure for this command is as follows:
Head	Len	Cmd	Control Word	Data	Checksum	Tail
0x01	xx (2 bytes)	0xb1	Control Word	data[]	xx	0x02

Control Word (1 byte):

0: Start saving (Wait for device response)
1: Transmit data
2: Transmission end

When Control Word is 0 or 2:

Data[0]: 0 for a normal image (no additional data), 1 for LED editor (additional data follows), 2 for sand painting, 3 for scroll animation

If it is an LED editor:

Data[1]: Speed (1 byte)
Data[2]: Length of the text (1 byte)
Data[3] onwards: File data (Data[2] * 2 bytes)

If it is a scroll animation:

Data[1]: Mode (1 byte)
Data[2]: Speed (2 bytes) (Data[2] = speed & 0xFF; Data[3] = speed >> 8)
Data[4]: Length (2 bytes) (Data[4] = len & 0xFF; Data[5] = len >> 8)

If Control Word is 1 (Transmit Data):

LEN (2 bytes): Current data length, must be a complete frame data.
Data: Image data

For sand painting data structure: Two bytes for speed (in milliseconds), followed by (two bytes for length + one image). Then, N groups of data (two bytes for the number of points, if it’s a color fill, it’s 0; no offset data in this case), followed by RGB color (three bytes), and N sets of point offsets (from left to right, top to bottom, starting from 0).

Device Response Command:

Head	Len	MainCmd	Cmd	AckCode	Checksum	Tail
0x01	xx (2 bytes)	0x4	0xb1	0x55	xx	0x02

---

## Modify user gif items (0xb6)

**URL:** https://docin.divoom-gz.com/web/#/5/295

**Content Length:** 626 characters

Welcome to the Divoom API

command description
This command is used to get the number of user-defined items or delete a specific item.
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0xb6	data	xx	0x02
DATA (1 byte): If DATA is 0xff, the device will return the current number of items. If DATA is any other value, the device will delete the corresponding item (numbered from 1).

Device Response Command:

Head	Len	MainCmd	Cmd	AckCode	item	Checksum	Tail
0x01	xx (2 bytes)	0x4	0xb6	0x55	xx	xx	0x02
Item (1 byte): The response will contain the item number, counting from left to right, then from top to bottom, starting from 1.

---

## App new user define (0x8c)

**URL:** https://docin.divoom-gz.com/web/#/5/296

**Content Length:** 1298 characters

Welcome to the Divoom API

command description
This command is for new user-defined image frame transmission. The data structure for this command varies based on the control word (Control_Word).
Head	Len	Cmd	Control word	Data	Checksum	Tail
0x01	xx (2 bytes)	0x8c	Control_Word	data[]	xx	0x02
Control_Word = 0 (Start Sending): Wait for the device to respond before sending data.

data[] format:

File Size (4 bytes): Total size of the file in little-endian format
index (1 bytes ):Indicates the index of the image frame, starting from 0.

The APP should wait for the device’s response before starting to send data. The device’s response is done using the “Set user gif” command.

Control_Word = 1 (Sending Data):
data[] format:
- File Total Length (4 bytes): Total length of the file in bytes
- File Offset ID (2 bytes): Little-endian value starting from 0
- File Data (256 bytes): Actual data to be sent (up to 256 bytes)


If the device requests retransmission of a data packet, the data structure will be:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x8c	0x55	data[]	xx	0x02
data[] format:
 - data[0]: Control_Word (1 byte): set to 1
 - data[1~2] Control Data (2 bytes): Offset value requesting a resend of data

Control_Word = 2 (Terminate Sending):
-no data to be sent

---

## App big64 user define (0x8d)

**URL:** https://docin.divoom-gz.com/web/#/5/297

**Content Length:** 1803 characters

Welcome to the Divoom API

command description
This command is used for 64 large canvas user-defined image frame transmission.
Head	Len	Cmd	Control word	Data	Checksum	Tail
0x01	xx (2 bytes)	0x8d	Control_Word	data[]	xx	0x02

Control_Word (1 byte):

0: Start sending. Wait for the device to respond before sending data.
1: Send data.
2: Terminate sending.
3: Delete a specific artwork.
4: Play a specific artwork.
5: Delete all files of a specific index.

Control_Word = 0 (Start Sending): Wait for the device to respond before sending data.

 data[] format:
 - File Size (4 bytes): Total size of the file in little-endian format
 - index (1 bytes ):Indicates the index of the image frame, starting from 0.
 - File Id: Unique ID of the file given by the APP.


The APP should wait for the device’s response before starting to send data. The device’s response is done using the SPP_APP_BIG64_USER_DEFINE command.

Control_Word = 1 (Sending Data):
data[] format:
- File Total Length (4 bytes): Total length of the file in bytes
- File Offset ID (2 bytes): Little-endian value starting from 0
- File Data (256 bytes): Actual data to be sent (up to 256 bytes)


If the device requests retransmission of a data packet, the data structure will be:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x8d	0x55	data[]	xx	0x02
data[] format:
 - data[0]: Control_Word (1 byte): set to 1
 - data[1~2] Control Data (2 bytes): Offset value requesting a resend of data


Control_Word = 2 (Terminate Sending):
-no data to be sent

Control_Word = 3 or 4 :

  data[] format:
  - File Id: Unique ID of the file given by the APP.
  - index (1 bytes ):Indicates the index of the image frame, starting from 0.

Control_Word = 5:
  - index (1 bytes ):Indicates the index of the image frame, starting from 0.

---

## App get user define info (0x8e)

**URL:** https://docin.divoom-gz.com/web/#/5/298

**Content Length:** 1057 characters

Welcome to the Divoom API

command description
This command is used for the 64 custom image frame ID upload function. When the APP connects to the device, it sends a request to the device, or when the device deletes some files, it proactively updates once.
Head	Len	Cmd	UserIndex	Checksum	Tail
0x01	xx (2 bytes)	0x8e	user_index	xx	0x02

user_index(1 bytes): Indicates the index of the image frame, starting from 0.

Device Response:

Head	Len	MainCmd	Cmd	Ackcode	ControlWord	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x8e	0x55	control_word	data[]	xx	0x02

Control_Word = 1:
data[] format:

 - User_index (1 byte): Indicates the index of the image frame, starting from 0.
 - Total (2 bytes): Total number of files in little-endian format.
 - Offset (2 bytes): Current offset in little-endian format.
 - Num (2 bytes): Number of files sent in the current response in little-endian format.
 - File id (4 bytes each * Num): Data containing the IDs of the files.


Control_Word = 2:

  User_index (1 byte): Indicates the index of the image frame, starting from 0.

---

## Set rhythm gif (0xb7)

**URL:** https://docin.divoom-gz.com/web/#/5/299

**Content Length:** 717 characters

Welcome to the Divoom API

command description
This command is used to set the related information for the rhythm animation.
Head	Len	Cmd	Pos	Tol	Id	Data	Checksum	Tail
0x01	xx (2 bytes)	0xb7	pos	tol	id	data[]	xx	0x02

data format:

pos (1 byte): Custom position of the animation, counting from left to right and top to bottom, starting from 1.
Tol_len (2 bytes): Total length of the data packet in little-endian format.
id (1 byte): Sequence number of the data packet being sent.
data[]: Data structure similar to divoom_image_encode_encode_mul_pic(https://github.com/DivoomDevelop/DivoomImageDecode.git), encoding the animation data. The data is fixed at 200 bytes, and the last packet contains the actual data size.

---

## App send eq gif (0x1b)

**URL:** https://docin.divoom-gz.com/web/#/5/300

**Content Length:** 870 characters

Welcome to the Divoom API

command description
This command is used for the app to send EQ rhythm animation to the device. The command packet format is the same as “Set rhythm gif”.
Head	Len	Cmd	Pos	Tol	Id	Data	Checksum	Tail
0x01	xx (2 bytes)	0x1b	pos	tol	id	data[]	xx	0x02

data format:

pos (1 byte): Custom position of the animation, counting from left to right and top to bottom, starting from 1.
Tol_len (2 bytes): Total length of the data packet in little-endian format.
id (1 byte): Sequence number of the data packet being sent.
data[]: Data structure similar to divoom_image_encode_encode_pic, encoding the animation data. The data is fixed at 200 bytes, and the last packet contains the actual data size.

This command is used to send EQ rhythm animations to the device for display. The device will use the provided animation data to show the EQ rhythm effect.

---

## Drawing mul pad ctrl (0x3a)

**URL:** https://docin.divoom-gz.com/web/#/5/301

**Content Length:** 1427 characters

Welcome to the Divoom API

command description
This command is used for multiple screen drawing pad control and is sent from the mobile app to the device.
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0x3a	data[]	xx	0x02

Data: The data field contains information about the drawing pad control:

data[0] (Byte 1): 屏的ID (Screen ID) - Specifies the ID of the screen. If it is a single screen, the ID is 0. For multiple screens, the ID represents the screen’s position from left to right and top to bottom, starting from 0.
data[1] (Byte 2): R - Red color component.
data[2] (Byte 3): G - Green color component.
data[3] (Byte 4): B - Blue color component.
data[4] (Byte 5): Number of points - Specifies the number of points to be drawn.
data[5] (Starting from Byte 6): Offset List - Contains the offset values for the points to be drawn. The offset values determine the position of the points on the screen, from left to right, starting from 0.

device responds:

Head	Len	MainCmd	Cmd	AckCode	CtrFlag	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x3a	0x55	ctrl_flag	xx	0x02

ctrflag: This field indicates whether the device should display the drawing or not.

If ctrflag is 1, it means that the device should display the drawing (normal display).
If ctrflag is 0, it means that the device was not on the drawing pad previously, and the app is requesting the device to send the entire drawing image (requesting to send the whole image).

---

## Drawing big pad ctrl (0x3b)

**URL:** https://docin.divoom-gz.com/web/#/5/302

**Content Length:** 1572 characters

Welcome to the Divoom API

command description
This command is used for controlling the large screen drawing pad. It is similar to the “Drawing mul pad ctrl (0x3A)”, but it adds the canvas width parameter.
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0x3b	data[]	xx	0x02

Data: The data field contains information about the drawing pad control:

data[0] (1 byte): The width of the canvas in terms of screen width (number of pixels divided by 16).
data[1] (Byte 1): Screen ID - Specifies the ID of the screen. If it is a single screen, the ID is 0. For multiple screens, the ID represents the screen’s position from left to right and top to bottom, starting from 0.
data[2] (Byte 2): R - Red color component.
data[3] (Byte 3): G - Green color component.
data[4] (Byte 4): B - Blue color component.
data[5] (Byte 5): Number of points - Specifies the number of points to be drawn.
data[6] (Starting from Byte 6): Offset List - Contains the offset values for the points to be drawn. The offset values determine the position of the points on the screen, from left to right, starting from 0.

device responds:

Head	Len	MainCmd	Cmd	AckCode	CtrFlag	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x3b	0x55	ctrl_flag	xx	0x02

ctrflag: This field indicates whether the device should display the drawing or not.

If ctrflag is 1, it means that the device should display the drawing (normal display).
If ctrflag is 0, it means that the device was not on the drawing pad previously, and the app is requesting the device to send the entire drawing image (requesting to send the whole image).

---

## Drawing pad ctrl (0x58)

**URL:** https://docin.divoom-gz.com/web/#/5/303

**Content Length:** 977 characters

Welcome to the Divoom API

command description
This command is used for controlling the large screen drawing pad. It is similar to the “Drawing mul pad ctrl (0x3A)”, but it adds the canvas width parameter.
Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0x58	data[]	xx	0x02

Data: The data field contains information about the drawing pad control:

data[0] (Byte 1): R - Red color component.
data[1] (Byte 2): G - Green color component.
data[2] (Byte 3): B - Blue color component.
data[4] (Byte 4): Number of points - Specifies the number of points to be drawn.
data[5] (Starting from Byte 5): Offset List - Contains the offset values for the points to be drawn. The offset values determine the position of the points on the screen, from left to right, starting from 0.

If the device is not in drawing mode when the command is received, it will respond with an acknowledgment (ACK) message.

Head	Len	MainCmd	Cmd	AckCode	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x58	0x55	xx	0x02

---

## Drawing pad exit (0x5a)

**URL:** https://docin.divoom-gz.com/web/#/5/304

**Content Length:** 336 characters

Welcome to the Divoom API

command description
This command is used for exiting the drawing pad and is sent from the mobile app to the device. It is primarily used to handle the scenario where the app exits the drawing pad, especially when the device is in a black screen state.
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x5a	xx	0x02

---

## Drawing mul encode single pic (0x5b)

**URL:** https://docin.divoom-gz.com/web/#/5/305

**Content Length:** 646 characters

Welcome to the Divoom API

command description

-This command is used for sending a single image encoded using divoom_image_encode_encode_mul_pic(https://github.com/DivoomDevelop/DivoomImageDecode.git) to multiple screens (panels). It is sent from the mobile app to the device.

Head	Len	Cmd	Id	Len	Data	Checksum	Tail
0x01	xx (2 bytes)	0x5b	id	len	data[]	xx	0x02
Id (1 byte): The ID of the screen (panel) where the image should be displayed. The ID is assigned from left to right and top to bottom. For example, the top-left screen has ID 0, the screen to its right has ID 1, and so on.
Len: The current data length.
Data: The encoded image data.

---

## Drawing mul encode pic (0x5c)

**URL:** https://docin.divoom-gz.com/web/#/5/306

**Content Length:** 1241 characters

Welcome to the Divoom API

command description

-This command is used for sending encoded animation data to multiple screens (panels) for later playback. It is sent from the mobile app to the device.

Head	Len	Cmd	Id	Tol	PicId	Data	Checksum	Tail
0x01	xx (2 bytes)	0x5c	id	tol	pic_id	pic_data[]	xx	0x02
Id (1 byte): The ID of the screen (panel) where the animation data should be displayed. The ID is assigned from left to right and top to bottom. For example, the top-left screen has ID 0, the screen to its right has ID 1, and so on.
Tol_len: The total length of the animation data.
pic_id (1 byte): The sequential ID of the animation data being sent.
pic_data: The encoded animation data in the structure of divoom_image_encode_encode_mul_pic(https://github.com/DivoomDevelop/DivoomImageDecode.git). The data size is fixed at 200 bytes, and the last packet contains the actual data size.

The mobile app sends this command to deliver the animation data to the device for later playback. The device receives the animation data but does not start playing it immediately. Instead, the app needs to send the command drawing mul encode gif play (0X6B) after sending all the animation data to instruct the device to start the animation playback.

---

## Drawing mul encode gif play (0x6b)

**URL:** https://docin.divoom-gz.com/web/#/5/307

**Content Length:** 295 characters

Welcome to the Divoom API

command description

-This command is used to instruct the device to start playing the animation that was previously sent using the Drawing mul encode gif command. It is sent from the mobile app to the device.

Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x6b	xx	0x02

---

## Drawing encode movie play (0x6c)

**URL:** https://docin.divoom-gz.com/web/#/5/308

**Content Length:** 557 characters

Welcome to the Divoom API

command description

-This command is used to instruct the device to play a single-screen movie or animation.

Head	Len	Cmd	FramkId	Len	Data	Checksum	Tail
0x01	xx (2 bytes)	0x6c	framk_id(2 bytes)	len (2 bytes)	data[]	xx	0x02
Framk_Id: The frame ID, a two-byte value representing the sequence number of the frame, starting from 0.
Len: The length of the current data in bytes (two bytes).
Data: The movie data, which has been encoded using divoom_image_encode_encode_mul_pic(https://github.com/DivoomDevelop/DivoomImageDecode.git).

---

## Drawing mul encode movie play (0x6d)

**URL:** https://docin.divoom-gz.com/web/#/5/309

**Content Length:** 702 characters

Welcome to the Divoom API

command description

-This command is used to instruct the device to play a single-screen movie or animation.

Head	Len	Cmd	Id	FramkId	Len	Data	Checksum	Tail
0x01	xx (2 bytes)	0x6d	id (1 bytes)	framk_id(2 bytes)	len (2 bytes)	data[]	xx	0x02
Id: One byte representing the screen ID. The screen ID is a sequential number from left to right and top to bottom, starting from 0, indicating which screen the frame data is intended for.
Framk_Id: The frame ID, a two-byte value representing the sequence number of the frame, starting from 0.
Len: The length of the current data in bytes (two bytes).
Data: The movie data, which has been encoded using divoom_image_encode_encode_pic.

---

## Drawing ctrl movie play (0x6e)

**URL:** https://docin.divoom-gz.com/web/#/5/310

**Content Length:** 487 characters

Welcome to the Divoom API

command description

-This command is used to control the movie playback on the device. The mobile app sends this command to the device.

Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0x6e	data[]	xx	0x02
DATA: One byte representing the control command for movie playback:
0x00: Exit movie mode - This command is used to exit the movie playback mode on the device.
0x01: Start movie playback - This command is used to start the movie playback on the device.

---

## Drawing mul pad enter (0x6f)

**URL:** https://docin.divoom-gz.com/web/#/5/311

**Content Length:** 473 characters

Welcome to the Divoom API

command description

-This command is used to enter the multiple screen mode drawing pad or perform a clear screen operation.It is sent from the mobile app to the device.

Head	Len	Cmd	Data	Checksum	Tail
0x01	xx (2 bytes)	0x6f	data[]	xx	0x02
Data: The data field contains RGB color information for the drawing pad.
data[0] (Byte 1): R - Red color component.
data[1] (Byte 2): G - Green color component.
data[2] (Byte 3): B - Blue color component.

---

## Sand paint ctrl (0x34)

**URL:** https://docin.divoom-gz.com/web/#/5/312

**Content Length:** 924 characters

Welcome to the Divoom API

command description

-The provided information describes the control command structure for managing sand painting on a Divoom device. Let’s break down the fields in the command:

Head	Len	Cmd	Ctrl	Data	Checksum	Tail
0x01	xx (2 bytes)	0x34	ctrl	data[]	xx	0x02

CTRL: This is a single-byte control field that determines the action to be taken for sand painting.

0: Initialize sand painting with accompanying data.
1: Reset sand painting and notify the device to load the first sand painting image.

DATA[]: This field contains additional data related to the sand painting control command.

ID(1 bytes): The device ID or screen ID. This field specifies the target device or screen for the sand painting operation.
Image Length(2 bytes): The length of the image data in bytes. It is divided into two bytes: pic_len & 0xFF and pic_len >> 8.
Image Data: The compressed image data for the sand painting.

---

## Pic scan ctrl (0x35)

**URL:** https://docin.divoom-gz.com/web/#/5/313

**Content Length:** 1263 characters

Welcome to the Divoom API

command description

-The provided information describes the control command structure for implementing a multi-screen scrolling effect on a Divoom device.

Head	Len	Cmd	Ctrl	Data	Checksum	Tail
0x01	xx (2 bytes)	0x35	ctrl	data[]	xx	0x02

ctrl: This is a single-byte control field that determines the type of operation to be performed for the multi-screen scrolling effect.

0: Control information for setting the scrolling mode and speed.
1: Control information for sending image data for the scrolling effect.

data[]: This field contains additional data related to the multi-screen scrolling control command.

For Ctrl = 0 (Setting Scrolling Mode and Speed):

Mode: A single byte indicating the scrolling mode.
Speed: A two-byte field specifying the speed of the scrolling effect in milliseconds. data[0] = time & 0xFF and data[1] = time >> 8.

For Ctrl = 1 (Sending Image Data for Scrolling Effect):

Tol_len: A two-byte field indicating the length of the entire data packet.
id: A single-byte field indicating the sequence number of the data packet.
data[]: This field contains image data encoded using divoom_image_encode_encode_pic. The data packet has a fixed size of 200 bytes, and the last packet contains the actual data size.

---

