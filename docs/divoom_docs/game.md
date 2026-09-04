# Game

## Send game shark (0x88)

**URL:** https://docin.divoom-gz.com/web/#/5/278

**Content Length:** 488 characters

Welcome to the Divoom API

command description
This command is used to get the current scene mode settings from the device.
Head	Len	Cmd	Checksum	Tail
0x01	xx (2 bytes)	0x88	xx	0x02

This command is used to send a game “Shake” action to the device. When the device receives this command, it will trigger the game’s “Shake” action, simulating a shaking motion in the game.

The command does not require any additional data fields. It is simply used as a trigger to perform the game action.

---

## Set game (0xa0)

**URL:** https://docin.divoom-gz.com/web/#/5/279

**Content Length:** 454 characters

Welcome to the Divoom API

command description
This command is used to enter or exit the game mode on the device.
Head	Len	Cmd	data	Checksum	Tail
0x01	xx (2 bytes)	0xa0	data	xx	0x02

Data Format:

1 byte: Game Mode (0: Off, 1: On)

When the device receives a value of 1 (On) for the game mode, it will enter the game mode. Conversely, when it receives a value of 0 (Off), it will exit the game mode. This command is used to toggle the device’s game mode.

---

## Set game ctrl info (0x17)

**URL:** https://docin.divoom-gz.com/web/#/5/280

**Content Length:** 1068 characters

Welcome to the Divoom API

command description
This command is used to send game control information from the app to the device when a key is pressed during the game.
Head	Len	Cmd	Key	Checksum	Tail
0x01	xx (2 bytes)	0x17	key	xx	0x02

Data Format:

1 byte: Key (The value represents the key pressed during the game. The possible values are defined as follows:
1: Left
2: Right
3: Up
4: Down
5: OK (Confirm)

the device connects to the APP and sends game-related information:

Head	Len	MainCmd	Cmd	Game type	Time	Score	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x17	xx (1 bytes)	xx (2 bytes)	xx (2 bytes)	xx	0x02

Data Format (Device to App):

1 byte: Game Type (The type of game played on the device, following the same enumeration as SPP_SET_GAME)
2 bytes: Time (Total time played in seconds, low byte first, high byte second)
2 bytes: Score (Highest score achieved in the game, low byte first, high byte second)

The device sends this information to the app after connecting, providing updates on the game progress and highest score achieved since the last synchronization.

---

## Set game ctrl key up info (0x21)

**URL:** https://docin.divoom-gz.com/web/#/5/281

**Content Length:** 1127 characters

Welcome to the Divoom API

command description
This command is used to send game control information from the app to the device when a key is released (up) during the game.
Head	Len	Cmd	key	Checksum	Tail
0x01	xx (2 bytes)	0x21	color[]	xx	0x02

Data Format:

enum
{
SPP_APP_KEY_LEFT = 1,
SPP_APP_KEY_RIGHT,
SPP_APP_KEY_UP ,
SPP_APP_KEY_DOWN,
SPP_APP_KEY_OK,
}SPP_APP_KEY_VALUE;

1 byte: Key (The value represents the key that was released during the game. The possible values are the same as those defined in the enumeration SPP_APP_KEY_VALUE for key presses.)

The device will not respond to this command. It is used to inform the device when a key has been released during the game.

For example, if the user presses the “Up” key, the app will send SPP_SEND_GAME_CTRL_INFO with the key value of SPP_APP_KEY_UP. When the user releases the “Up” key, the app will send SPP_SEND_GAME_CTRL_KEY_UP_INFO with the same key value of SPP_APP_KEY_UP to notify the device that the key has been released.

This command helps in handling key events during the game and ensures that the device knows when a key press or release has occurred.

---

