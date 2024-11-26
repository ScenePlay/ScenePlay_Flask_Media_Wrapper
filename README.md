ScenePlay Installation and User Guide
=====================================

ScenePlay is a customizable media controller designed for enhancing tabletop gaming sessions with immersive atmospheres. It integrates sound, video, and LED lighting control, making your gaming environment more engaging. Follow this guide to set up ScenePlay on your system.

1. Prerequisites
-----------------
Ensure you have the following before starting:
- A Raspberry Pi with a fresh Raspberry Pi OS installation, or an old computer running Mint OS.
- Make sure SSH is enabled
- Optional VNC Server (Makes it much easier to manage)
- Optional Disable IP V6 (not needed)
- Optional Set your IP4 to a static IP address. 
- A stable internet connection.
- Basic familiarity with the Linux command line.
- Setup your PI https://youtu.be/aG3hmzW03cs?si=4im_tgTbxHoVPVMD


2. Installation Steps
---------------------

Step 1: System Preparation
1. Open a terminal on your Computer ssh user@ipaddress.
2. Enter 
      - sudo visudo
      - After root user entry paste ex. sammy   ALL=(ALL) NOPASSWD:ALL
      - username  ALL=(ALL) NOPASSWD:ALL
      - Save and exit 
3. Update and upgrade your system:
   sudo apt-get update && sudo apt-get -y upgrade

Step 2: Download ScenePlay Files
Clone or copy the ScenePlay project files to your Raspberry Pi. Make sure when cloning to be in your /home/user directory. The application may break if not in this location. (Sorry)
    
    git clone https://github.com/ScenePlay/ScenePlay_Flask_Media_Wrapper ScenePlay

    Later use this to get upgrades:
    (If you have made changes to the files) git -C ScenePlay stash 
    git -C ScenePlay pull

Step 3: Install Dependencies
1. Navigate to the directory (cd ~/ScenePlay)containing `requirements.sh` and make the script executable:
   chmod +x requirements.sh
2. Run the script to install required packages and set up the Python virtual environment:
   ./requirements.sh
   This will install essential tools like:
   - mpg123, mpv, and sqlite3 for media playback and database management.
   - Python libraries including Flask, SQLAlchemy, and GTTS for web server and audio features.
   - Raspberry Pi-specific libraries such as rpi_ws281x and adafruit-circuitpython-neopixel for LED control.

Step 4: (This will run Automatically but you may need to execute it manually) Enable Auto-Start
1. Navigate to the `ScenePlay/supportFiles` directory.
2. Make the `setupAutoStart.sh` script executable:
   chmod +x setupAutoStart.sh
3. Run the script to set up auto-start and system services:
   ./setupAutoStart.sh

3. Usage
--------

Starting ScenePlay
Once the installation is complete, ScenePlay should start automatically on boot. If it doesn't, you can manually start it using the terminal:
cd ~/ScenePlay
source ~/ScenePlay/bin/activate
python3 app.py -flask

Accessing the Interface
- Open a web browser and navigate to the Raspberry Pi’s IP address (e.g., http://ipaddress).
- This interface allows you to control media playback and LED settings.

4. Features
-----------
- Audio and Video Playback: Use MPV and MPG123 for seamless media playback.
- LED Lighting: Control WLED or directly connected LED strips.
- Web Interface: Manage settings and media via an easy-to-use browser interface.
- Auto-Start and Watchdog: Ensures ScenePlay runs reliably at startup.

5. Troubleshooting
-------------------
- Dependencies not installed? Rerun `requirements.sh` to ensure all required tools and libraries are installed.
- Service not starting? Check the status of the `sceneplay_watchdog` service:
  systemctl --user status sceneplay_watchdog.service
- Interface not accessible? Ensure the correct IP and port are used. Verify that nginx is running:
  sudo systemctl status nginx

6. Chrome Extension
-------------------
Having access to youtube.com is a must for this application. Access your content using the chrome extension located in the /ChromeExt folder.
Goto chrome://extensions/ and set your browerser in Developer Mode. Then click on "Load Unpacked" and select the /ChromeExt folder.
The extension only will work on YouTube pages.

You can also do it one at a time in Utilites section of ScenePlay, but it makes it much easier using the Chrome Extension.

Have fun. Don't Panic!!
