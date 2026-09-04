# Timeplan

## Set time manage info (0x56)

**URL:** https://docin.divoom-gz.com/web/#/5/256

**Content Length:** 1246 characters

Welcome to the Divoom API

command description
This command is used to set time management information. Each time, only one record can be set.
Head	Len	Cmd	data	Checksum	Tail
0x01	xx (2 bytes)	0x56	data[]	xx	0x02

Data[] Format:

Uint8 tol: Total number of records to be set.
Uint8 ID: Record identifier, corresponding to the index 0, 1, 2, …, 9 for each record.
Uint8 start_hour: Starting hour (0-23).
Uint8 start_min: Starting minute (0-59).
Uint8 end_hour: Ending hour (0-23).
Uint8 end_min: Ending minute (0-59).
Uint8 tol_time: Total time in minutes. This field only has a value in the sports mode; for other modes, it will be set to 0.
Uint8 voice_on_off: Voice alarm switch; 1 for ON, 0 for OFF.
Uint8 disp_mode: Display mode.
Uint8 cyc_mode: Cycle mode.
Uint16 pic_len: Size of the picture data.
Uint8 pic_data[]: Picture data.

Note: The actual data length of the packet will depend on the total number of records (tol) and the size of the picture data (pic_len). The data should be filled accordingly.

Please note that the actual structure of the data may vary depending on the device’s specific implementation, and additional information may be required to understand the exact meaning of some fields (such as disp_mode and cyc_mode).

---

## Page 2

**URL:** https://docin.divoom-gz.com/web/#/5/257

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

