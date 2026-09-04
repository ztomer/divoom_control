# Tool

## Get tool info (0x71)

**URL:** https://docin.divoom-gz.com/web/#/5/264

**Content Length:** 2022 characters

Welcome to the Divoom API

command description
This command is used to get information about the tools available in the device. The data format for this command is as follows:
Head	Len	Cmd	Tool type	Checksum	Tail
0x01	xx (2 bytes)	0x71	tool type	xx	0x02

tool type:

DIVOOM_DISP_WATCH_MODE = 0: Timer function
DIVOOM_DISP_SCORE_MODE = 1: Score function
DIVOOM_DISP_NOISE_MODE = 2: Noise statistics function
0xFF: Not in any of the above game modes

Device response command:

Head	Len	MainCmd	Cmd	AckCode	Data	Checksum	Tail
0x01	xx (2 bytes)	0x4	0x71	0x55	data[]	xx	0x02

The data format in the response will be based on the value of the game_type. The possible values for game_type are:

DIVOOM_DISP_WATCH_MODE = 0: Timer function
DIVOOM_DISP_SCORE_MODE = 1: Score function
DIVOOM_DISP_NOISE_MODE = 2: Noise statistics function
0xFF: Not in any of the above game modes

Based on the value of game_type, the response data (Data[]) will have different formats:

If game_type is DIVOOM_DISP_WATCH_MODE = 0 (Timer function):

Data[0]: The status of the timer: 0 for paused, 1 for started, 2 for reset, 3 for entering the stopwatch mode.

If game_type is DIVOOM_DISP_SCORE_MODE = 1 (Score function):

Data[0]: The status of the score tool (score_on_off): 0 for off, 1 for on.
Data[1]: The low byte of the red team’s score (score_red_score).
Data[2]: The high byte of the red team’s score (score_red_score).
Data[3]: The low byte of the blue team’s score (score_blue_score).
Data[4]: The high byte of the blue team’s score (score_blue_score).

If game_type is DIVOOM_DISP_NOISE_MODE = 2 (Noise statistics function):

Data[0]: The current noise status: 1 for start, 2 for stop.

If game_type is DIVOOM_DISP_COUNT_TIME_DOWN = 3 (Countdown timer function):

Data[0]: The current mode status: 0 for start, 1 for cancel.
Data[1]: The minutes remaining in the countdown.
Data[2]: The seconds remaining in the countdown.

The response data will include information about the specified tool or game mode based on the provided game_type.

---

## Set tool info (0x72)

**URL:** https://docin.divoom-gz.com/web/#/5/265

**Content Length:** 2048 characters

Welcome to the Divoom API

command description

This command is used to set information for the tools (games) available in the device. The data format for this command is as follows:

Head	Len	Cmd	data	Checksum	Tail
0x01	xx (2 bytes)	0x72	data[]	xx	0x02

The data format for this command is as follows:

uint8 game_mode_index: The index representing the specific game mode or tool for which information is to be set. The possible values are:
DIVOOM_DISP_WATCH_MODE = 0: Timer function
DIVOOM_DISP_SCORE_MODE = 1: Score function
DIVOOM_DISP_NOISE_MODE = 2: Noise statistics function
DIVOOM_DISP_COUNT_TIME_DOWN = 3: Countdown timer function

Based on the value of game_mode_index, the data structure for the command will differ:

If game_mode_index is DIVOOM_DISP_WATCH_MODE = 0 (Timer function):

uint8 Ctrl_flag: This flag controls the timer function. The possible values are:
0: Pause the timer
1: Start the timer
2: Reset the timer

If game_mode_index is DIVOOM_DISP_SCORE_MODE = 1 (Score function):

uint8 on_off: This flag controls the score function. The possible values are:
0: Exit the score function
1: Start the score function
uint8 red_score_low: The low 8 bits of the red team’s score.
uint8 red_score_high: The high 8 bits of the red team’s score.
uint8 blue_score_low: The low 8 bits of the blue team’s score.
uint8 blue_score_high: The high 8 bits of the blue team’s score.

If game_mode_index is DIVOOM_DISP_NOISE_MODE = 2 (Noise statistics function):

uint8 ctrl_flag: This flag controls the noise statistics function. The possible values are:
1: Start the noise statistics
2: Stop the noise statistics

If game_mode_index is DIVOOM_DISP_COUNT_TIME_DOWN = 3 (Countdown timer function):

uint8 ctrl_flag: This flag controls the countdown timer function. The possible values are:

0: Start the countdown
1: Cancel the countdown
2: Pause/play the countdown (this is opposite to the value used in SPP_GET_TOOL_INFO)

uint8 min: The minutes remaining in the countdown.

uint8 second: The seconds remaining in the countdown (maximum 59).

---

